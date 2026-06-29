"""Live product-route adapter for eval trials."""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from roboclaws.evals.dependencies import dependency_failure, resolve_artifact_dependencies
from roboclaws.evals.live_artifacts import (
    discover_live_surface_run_dir,
    load_live_eval_json,
)
from roboclaws.evals.live_timeout import (
    LiveEvalTimeoutError,
    cleanup_timed_out_live_children,
    live_timeout_snapshot,
)
from roboclaws.evals.models import (
    MISSING_NOT_APPLICABLE,
    MISSING_SENTINELS,
    MISSING_UNAVAILABLE,
    EvalResult,
    EvalSample,
    EvalTrial,
)
from roboclaws.household.backend_contract import SYNTHETIC_BACKEND
from roboclaws.launch.backends import BACKEND_SPECS
from roboclaws.launch.catalog import SURFACE_SPECS
from roboclaws.launch.goals import normalize_goal_contract
from roboclaws.launch.intents import TASK_INTENT_SPECS
from roboclaws.launch.map_bundles import molmospaces_nav2_map_bundle_path

REPO_ROOT = Path(__file__).resolve().parents[2]
ProductRun = Callable[..., dict[str, Any]]
DEFAULT_LIVE_TIMEOUT_S = 3600.0
DEFAULT_LIVE_TIMEOUT_COMPLETION_GRACE_S = 30.0


@dataclass(frozen=True)
class LiveTrialHooks:
    """Runner-owned grading hooks needed after a live surface run completes."""

    failed_result_from_dependency: Callable[[EvalTrial, Path, dict[str, Any]], EvalResult]
    blocked_result_from_exception: Callable[[EvalTrial, Exception], EvalResult]
    grade_trial: Callable[..., dict[str, Any]]
    status_from_graders: Callable[[dict[str, Any]], tuple[str, str]]
    artifact_paths: Callable[[Path], dict[str, Any]]
    metrics_from_graders: Callable[..., dict[str, Any]]


def run_live_eval_trial(
    *,
    sample: EvalSample,
    trial: EvalTrial,
    run_dir: Path,
    budget: str,
    repetition_index: int,
    sample_artifacts: dict[str, dict[str, Any]],
    agent_engine: str,
    provider_profile: str,
    model: str | None,
    live_timeout_s: float | None,
    live_product_runner: ProductRun,
    hooks: LiveTrialHooks,
) -> EvalResult:
    """Run and grade one live-agent eval trial through the product surface."""

    try:
        dependency_artifacts = resolve_artifact_dependencies(
            sample,
            repetition_index=repetition_index,
            sample_artifacts=sample_artifacts,
        )
        failure = dependency_failure(dependency_artifacts)
        if failure is not None:
            return hooks.failed_result_from_dependency(trial, run_dir, failure)
        run_result = live_product_runner(
            **live_product_run_kwargs(
                sample,
                run_dir=run_dir,
                budget=budget,
                dependency_artifacts=dependency_artifacts,
                agent_engine=agent_engine,
                provider_profile=provider_profile,
                model=model,
                live_timeout_s=live_timeout_s,
            )
        )
        effective_run_dir = _live_eval_effective_run_dir(
            run_result,
            trial_run_dir=run_dir,
        )
    except Exception as exc:  # noqa: BLE001 - eval packets must classify runner failures.
        return hooks.blocked_result_from_exception(trial, exc)

    grader_outputs = hooks.grade_trial(
        sample=sample,
        run_dir=effective_run_dir,
        run_result=run_result,
        dependency_artifacts=dependency_artifacts,
    )
    status, failure_class = hooks.status_from_graders(grader_outputs)
    artifacts = hooks.artifact_paths(effective_run_dir)
    metrics = hooks.metrics_from_graders(
        grader_outputs,
        status=status,
        run_result=run_result,
    )
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


def run_live_surface_product(**kwargs: Any) -> dict[str, Any]:
    """Run one live eval trial through the public surface runner and load artifacts."""

    run_dir = Path(kwargs["output_dir"])
    sample_run_root = run_dir / "surface-run"
    sample_run_root.mkdir(parents=True, exist_ok=True)
    sample_run_dir = live_surface_run_dir(kwargs, output_dir=sample_run_root)
    command = live_surface_command(kwargs, output_dir=sample_run_root)
    env = live_surface_env(kwargs, base_env=os.environ)
    timeout_s = explicit_live_surface_timeout_s(kwargs)
    started_wall_time_s = time.time()
    started = time.monotonic()
    record: dict[str, Any] = {
        "command": command,
        "returncode": None,
        "stdout": "",
        "stderr": "",
        "effective_run_dir": str(sample_run_dir),
    }
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as exc:
        timeout_stdout = _subprocess_text_output(exc.stdout)
        timeout_stderr = _subprocess_text_output(exc.stderr)
        sample_run_dir = discover_live_surface_run_dir(
            kwargs,
            output_dir=sample_run_root,
            fallback_run_dir=sample_run_dir,
            stdout=timeout_stdout,
            started_wall_time_s=started_wall_time_s,
        )
        sample_run_dir = wait_for_timed_out_live_surface_artifact(
            kwargs,
            output_dir=sample_run_root,
            effective_run_dir=sample_run_dir,
            started_wall_time_s=started_wall_time_s,
            allow_open_ended_checker_failure=_is_open_ended_eval_sample(kwargs),
        )
        record.update(
            {
                "returncode": "timeout",
                "stdout": timeout_stdout,
                "stderr": timeout_stderr,
                "timeout_s": timeout_s,
                "timeout_completion_grace_s": live_timeout_completion_grace_s(),
                "effective_run_dir": str(sample_run_dir),
                "live_status": _load_json(sample_run_dir / "live_status.json"),
            }
        )
        record["timeout_debug_snapshot"] = live_timeout_snapshot(
            sample_run_dir,
            live_status=record["live_status"],
            timeout_s=timeout_s,
        )
        run_result_path = sample_run_dir / "run_result.json"
        run_result = _load_json(run_result_path)
        if run_result and _live_surface_already_complete(
            sample_run_dir,
            allow_open_ended_checker_failure=_is_open_ended_eval_sample(kwargs),
            require_terminal_status=False,
        ):
            record["returncode"] = "timeout_after_completion"
            _write_live_eval_command_record(run_dir / "live_eval_command.json", record)
            run_result["eval_effective_run_dir"] = str(sample_run_dir)
            return run_result
        record["timeout_child_cleanup"] = cleanup_timed_out_live_children(sample_run_dir)
        _write_live_eval_command_record(run_dir / "live_eval_command.json", record)
        raise LiveEvalTimeoutError(
            f"live eval trial timed out after {timeout_s:g}s",
            timeout_s=timeout_s,
            effective_run_dir=sample_run_dir,
            live_status=record["live_status"],
            timeout_debug_snapshot=record["timeout_debug_snapshot"],
            command_record=record,
        ) from exc

    sample_run_dir = discover_live_surface_run_dir(
        kwargs,
        output_dir=sample_run_root,
        fallback_run_dir=sample_run_dir,
        stdout=completed.stdout,
        started_wall_time_s=started_wall_time_s,
    )
    record.update(
        {
            "returncode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "effective_run_dir": str(sample_run_dir),
            "live_status": _load_json(sample_run_dir / "live_status.json"),
        }
    )
    if completed.returncode != 0:
        _write_live_eval_command_record(run_dir / "live_eval_command.json", record)
        run_result = _recover_eval_run_result_after_nonzero_checker_exit(
            kwargs,
            sample_run_dir=sample_run_dir,
        )
        if run_result:
            sample_run_dir = wait_for_live_surface_completion(
                kwargs,
                output_dir=sample_run_root,
                effective_run_dir=sample_run_dir,
                elapsed_s=time.monotonic() - started,
                allow_open_ended_checker_failure=True,
                started_wall_time_s=started_wall_time_s,
            )
            run_result["eval_effective_run_dir"] = str(sample_run_dir)
            return run_result
        message = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"live surface run failed with exit {completed.returncode}: {message}")
    sample_run_dir = wait_for_live_surface_completion(
        kwargs,
        output_dir=sample_run_root,
        effective_run_dir=sample_run_dir,
        elapsed_s=time.monotonic() - started,
        allow_open_ended_checker_failure=_is_open_ended_eval_sample(kwargs),
        started_wall_time_s=started_wall_time_s,
    )
    record["effective_run_dir"] = str(sample_run_dir)
    record["live_status"] = _load_json(sample_run_dir / "live_status.json")
    _write_live_eval_command_record(run_dir / "live_eval_command.json", record)
    run_result_path = sample_run_dir / "run_result.json"
    run_result = _load_json(run_result_path)
    if not run_result:
        raise RuntimeError(f"live surface run finished without {run_result_path}")
    run_result["eval_effective_run_dir"] = str(sample_run_dir)
    return run_result


def live_surface_command(kwargs: dict[str, Any], *, output_dir: Path) -> list[str]:
    """Build the public surface command for one live eval trial."""

    sample: EvalSample | None = kwargs.get("eval_sample")
    evidence_lane = live_evidence_lane(kwargs)
    command = [
        sys.executable,
        "-m",
        "roboclaws.cli.main",
        "run",
        "surface",
        "surface=household-world",
        f"world={sample.world if sample else 'molmospaces/val_0'}",
        f"backend={_public_backend_from_implementation(str(kwargs.get('backend') or ''))}",
        f"agent_engine={kwargs['agent_engine']}",
        f"provider_profile={kwargs['provider_profile']}",
        f"evidence_lane={evidence_lane}",
        f"seed={kwargs['seed']}",
        f"output_dir={output_dir}",
        f"run_dir={live_surface_run_dir(kwargs, output_dir=output_dir)}",
        f"scene_source={_live_surface_scene_source(kwargs)}",
        f"scene_index={_live_surface_scene_index(kwargs)}",
    ]
    camera_labeler = live_camera_labeler(kwargs, evidence_lane=evidence_lane)
    if camera_labeler:
        command.append(f"camera_labeler={camera_labeler}")
    if sample is not None and sample.preset not in {"", MISSING_NOT_APPLICABLE}:
        command.append(f"preset={sample.preset}")
    elif sample is not None and sample.intent == "map-build":
        command.append("preset=map-build")
    if _is_smoke_budget(kwargs):
        command.append("run_preset=smoke")
    else:
        relocation_count = _generated_mess_count(kwargs)
        if relocation_count:
            command.append("scenario_setup=relocate-cleanup-related-objects")
            command.append(f"relocation_count={relocation_count}")
    runtime_map_prior = str(kwargs.get("runtime_map_prior_path") or "")
    if runtime_map_prior:
        command.append(f"runtime_map_prior={runtime_map_prior}")
    goal_contract = str(kwargs.get("goal_contract_json") or "")
    if goal_contract:
        command.append(f"goal_contract_json={goal_contract}")
    task_prompt = str(kwargs.get("task_prompt") or "")
    if task_prompt and (sample is None or sample.prompt not in {"", MISSING_NOT_APPLICABLE}):
        command.append(f"prompt={task_prompt}")
    return command


def live_surface_run_dir(kwargs: dict[str, Any], *, output_dir: Path) -> Path:
    """Return the preferred artifact directory for one public surface run."""

    return output_dir / f"seed-{int(kwargs['seed'])}"


def wait_for_live_surface_completion(
    kwargs: dict[str, Any],
    *,
    output_dir: Path,
    effective_run_dir: Path,
    elapsed_s: float = 0.0,
    poll_s: float = 1.0,
    allow_open_ended_checker_failure: bool = False,
    started_wall_time_s: float | None = None,
) -> Path:
    """Validate foreground live-product artifacts after the public route exits."""

    if _live_surface_already_complete(
        effective_run_dir,
        allow_open_ended_checker_failure=allow_open_ended_checker_failure,
        require_terminal_status=False,
    ):
        return effective_run_dir
    return effective_run_dir


def _live_surface_already_complete(
    effective_run_dir: Path,
    *,
    allow_open_ended_checker_failure: bool,
    require_terminal_status: bool,
) -> bool:
    if (effective_run_dir / "run_result.json").is_file() and not require_terminal_status:
        status = _load_json(effective_run_dir / "live_status.json")
        if status:
            exit_status = status.get("exit_status")
            if exit_status not in {None, 0}:
                if allow_open_ended_checker_failure and _is_checker_failure(status):
                    return True
                _raise_for_terminal_live_status(effective_run_dir, status)
        return True
    return _live_surface_run_is_terminal(
        effective_run_dir,
        allow_open_ended_checker_failure=allow_open_ended_checker_failure,
    )


def live_surface_timeout_s(kwargs: dict[str, Any]) -> float:
    timeout_s = kwargs.get("live_timeout_s")
    if timeout_s is None:
        return DEFAULT_LIVE_TIMEOUT_S
    return _positive_timeout_value(timeout_s, "live_timeout_s")


def explicit_live_surface_timeout_s(kwargs: dict[str, Any]) -> float | None:
    timeout_s = kwargs.get("live_timeout_s")
    if timeout_s is None:
        return None
    return _positive_timeout_value(timeout_s, "live_timeout_s")


def _live_surface_wait_deadline(*, timeout_s: float, elapsed_s: float) -> float:
    remaining_s = max(timeout_s - max(elapsed_s, 0.0), 0.0)
    return time.monotonic() + remaining_s


def wait_for_timed_out_live_surface_artifact(
    kwargs: dict[str, Any],
    *,
    output_dir: Path,
    effective_run_dir: Path,
    poll_s: float = 1.0,
    allow_open_ended_checker_failure: bool = False,
    started_wall_time_s: float | None = None,
) -> Path:
    """Return the last discovered run dir after a foreground subprocess timeout."""

    return effective_run_dir


def live_timeout_completion_grace_s() -> float:
    raw = str(os.environ.get("ROBOCLAWS_LIVE_EVAL_TIMEOUT_COMPLETION_GRACE_S") or "").strip()
    if not raw:
        return DEFAULT_LIVE_TIMEOUT_COMPLETION_GRACE_S
    return _non_negative_timeout_value(raw, "ROBOCLAWS_LIVE_EVAL_TIMEOUT_COMPLETION_GRACE_S")


def _non_negative_timeout_value(value: object, setting_name: str) -> float:
    return _finite_timeout_value(
        value,
        setting_name,
        allow_zero=True,
    )


def _positive_timeout_value(value: object, setting_name: str) -> float:
    return _finite_timeout_value(
        value,
        setting_name,
        allow_zero=False,
    )


def _finite_timeout_value(
    value: object,
    setting_name: str,
    *,
    allow_zero: bool,
) -> float:
    lower_bound = "non-negative" if allow_zero else "positive"
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(_timeout_value_error(setting_name, lower_bound, value)) from exc
    if not math.isfinite(parsed) or parsed < 0 or (parsed == 0 and not allow_zero):
        raise ValueError(_timeout_value_error(setting_name, lower_bound, value))
    return parsed


def _timeout_value_error(
    setting_name: str,
    lower_bound_description: str,
    value: object,
) -> str:
    return (
        f"{setting_name} must be a {lower_bound_description} finite number of seconds, "
        f"got {value!r}"
    )


def live_product_run_kwargs(
    sample: EvalSample,
    *,
    run_dir: Path,
    budget: str,
    dependency_artifacts: dict[str, Any] | None,
    agent_engine: str,
    provider_profile: str,
    model: str | None,
    live_timeout_s: float | None,
) -> dict[str, Any]:
    """Return product-run kwargs plus live-agent routing metadata."""

    kwargs = product_run_kwargs(
        sample,
        run_dir=run_dir,
        budget=budget,
        dependency_artifacts=dependency_artifacts,
    )
    kwargs.update(
        {
            "eval_sample": sample,
            "agent_engine": agent_engine,
            "provider_profile": provider_profile,
            "model": model,
            "live_timeout_s": live_timeout_s,
        }
    )
    return kwargs


def product_run_kwargs(
    sample: EvalSample,
    *,
    run_dir: Path,
    budget: str,
    dependency_artifacts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return shared cleanup product-run kwargs for direct and live eval trials."""

    map_build = sample.intent == "map-build" or sample.preset == "map-build"
    kwargs: dict[str, Any] = {
        "output_dir": run_dir,
        "seed": sample.seed,
        "task_prompt": task_prompt(sample),
        "backend": implementation_backend(sample, budget=budget),
        "evidence_lane": evidence_lane(sample, budget=budget),
        "map_build": map_build,
        "generated_mess_count": generated_mess_count(sample),
        "scene_source": scene_source(sample),
        "scene_index": scene_index(sample),
        "run_metadata_overrides": {
            "eval_sample_id": sample.sample_id,
            "eval_sample_version": sample.version,
            "eval_suite_runner": "roboclaws.evals.runner",
        },
    }
    if kwargs["evidence_lane"] == "camera-grounded-labels":
        kwargs["visual_grounding"] = camera_labeler(sample)
    if kwargs["backend"] in {SYNTHETIC_BACKEND, "molmospaces_subprocess"}:
        kwargs["map_bundle_dir"] = str(
            molmospaces_nav2_map_bundle_path(
                scene_source=kwargs["scene_source"],
                scene_index=kwargs["scene_index"],
            )
        )
    goal_contract = _goal_contract_json(sample)
    if goal_contract:
        kwargs["goal_contract_json"] = goal_contract
    runtime_map_prior = str((dependency_artifacts or {}).get("runtime_map_prior_path") or "")
    if runtime_map_prior:
        kwargs["runtime_map_prior_path"] = runtime_map_prior
    return kwargs


def implementation_backend(sample: EvalSample, *, budget: str) -> str:
    if budget == "smoke":
        return SYNTHETIC_BACKEND
    backend = BACKEND_SPECS.get(sample.backend)
    if backend is None:
        return sample.backend
    return backend.implementation_backend


def evidence_lane(sample: EvalSample, *, budget: str) -> str:
    if budget == "smoke":
        return "smoke"
    return sample.evidence_lane


def camera_labeler(sample: EvalSample) -> str:
    if sample.evidence_lane != "camera-grounded-labels":
        return ""
    if sample.camera_labeler not in MISSING_SENTINELS:
        return sample.camera_labeler
    return "grounding-dino"


def task_prompt(sample: EvalSample) -> str:
    if sample.prompt not in {"", MISSING_NOT_APPLICABLE, MISSING_UNAVAILABLE}:
        return sample.prompt
    if sample.intent == "map-build":
        return "帮我建立这个房间的 Runtime Metric Map"
    return "帮我收拾这个房间"


def generated_mess_count(sample: EvalSample) -> int:
    reference = sample.private_goal_reference
    if "generated_mess_count" in reference:
        return _non_negative_int_value(
            reference.get("generated_mess_count"),
            "private_goal_reference.generated_mess_count",
        )
    launch_overrides = sample.launch_overrides or {}
    for key in ("generated_mess_count", "relocation_count"):
        value = launch_overrides.get(key)
        if value is not None:
            return _non_negative_int_value(value, f"launch_overrides.{key}")
    if sample.intent == "map-build":
        return 0
    return 10


def scene_source(sample: EvalSample) -> str:
    launch_overrides = sample.launch_overrides or {}
    if "scene_source" not in launch_overrides:
        return "procthor-10k-val"
    return _non_empty_string_value(
        launch_overrides.get("scene_source"),
        "launch_overrides.scene_source",
    )


def scene_index(sample: EvalSample) -> int:
    launch_overrides = sample.launch_overrides or {}
    if "scene_index" not in launch_overrides:
        return 0
    return _non_negative_int_value(
        launch_overrides.get("scene_index"),
        "launch_overrides.scene_index",
    )


def _goal_contract_json(sample: EvalSample) -> str:
    launch_overrides = sample.launch_overrides or {}
    override = str(launch_overrides.get("goal_contract_json") or "")
    if override:
        return override
    if sample.intent not in TASK_INTENT_SPECS:
        return ""
    surface = SURFACE_SPECS.get(sample.surface)
    if surface is None:
        return ""
    return normalize_goal_contract(
        surface=surface,
        intent=TASK_INTENT_SPECS[sample.intent],
        raw_prompt="" if sample.prompt in MISSING_SENTINELS else sample.prompt,
    ).to_json()


def live_surface_env(kwargs: dict[str, Any], *, base_env: Any) -> dict[str, str]:
    """Return environment overrides for the selected live agent engine."""

    env = dict(base_env)
    provider_profile = str(kwargs.get("provider_profile") or "")
    if provider_profile:
        if kwargs["agent_engine"] == "openai-agents-sdk":
            env["ROBOCLAWS_PROVIDER_PROFILE"] = provider_profile
    model = str(kwargs.get("model") or "")
    if model:
        if kwargs["agent_engine"] == "openai-agents-sdk":
            env["ROBOCLAWS_CODEX_MODEL"] = model
    return env


def live_evidence_lane(kwargs: dict[str, Any]) -> str:
    lane = str(kwargs.get("evidence_lane") or "")
    if lane == "smoke":
        return "world-public-labels"
    return lane or "world-public-labels"


def live_camera_labeler(kwargs: dict[str, Any], *, evidence_lane: str) -> str:
    """Return the public camera labeler argument for camera-grounded live evals."""

    if evidence_lane != "camera-grounded-labels":
        return ""
    sample = kwargs.get("eval_sample")
    if isinstance(sample, EvalSample) and sample.camera_labeler not in MISSING_SENTINELS:
        return sample.camera_labeler
    labeler = str(kwargs.get("camera_labeler") or "")
    if labeler and labeler not in MISSING_SENTINELS:
        return labeler
    visual_grounding = str(kwargs.get("visual_grounding") or "")
    if visual_grounding and visual_grounding not in MISSING_SENTINELS:
        return visual_grounding
    return "grounding-dino"


def _is_smoke_budget(kwargs: dict[str, Any]) -> bool:
    return str(kwargs.get("evidence_lane") or "") == "smoke"


def _generated_mess_count(kwargs: dict[str, Any]) -> int:
    value = kwargs.get("generated_mess_count")
    if value is None or value == "":
        return 0
    return _non_negative_int_value(value, "generated_mess_count")


def _live_surface_scene_index(kwargs: dict[str, Any]) -> int:
    return _non_negative_int_value(kwargs["scene_index"], "scene_index")


def _live_surface_scene_source(kwargs: dict[str, Any]) -> str:
    return _non_empty_string_value(kwargs["scene_source"], "scene_source")


def _non_empty_string_value(value: object, setting_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{setting_name} must be a non-empty string, got {value!r}")
    return value


def _non_negative_int_value(value: object, setting_name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{setting_name} must be a non-negative integer, got {value!r}")
    if isinstance(value, int):
        if value < 0:
            raise ValueError(f"{setting_name} must be a non-negative integer, got {value!r}")
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("+"):
            text = text[1:]
        if text.isdecimal():
            return int(text)
    raise ValueError(f"{setting_name} must be a non-negative integer, got {value!r}")


def _public_backend_from_implementation(backend: str) -> str:
    if backend in {MISSING_NOT_APPLICABLE, MISSING_UNAVAILABLE, ""}:
        return "mujoco"
    if backend == "api_semantic_synthetic":
        return "mujoco"
    for spec in BACKEND_SPECS.values():
        if spec.implementation_backend == backend:
            return spec.id
    return backend


def _load_json(path: Path) -> dict[str, Any]:
    return load_live_eval_json(path)


def _subprocess_text_output(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _live_eval_effective_run_dir(run_result: object, *, trial_run_dir: Path) -> Path:
    if not isinstance(run_result, dict):
        raise ValueError("live eval run_result must be an object")
    if "eval_effective_run_dir" not in run_result:
        raise ValueError("live eval run_result is missing eval_effective_run_dir")
    raw_path = run_result.get("eval_effective_run_dir")
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError(f"eval_effective_run_dir must be a non-empty string, got {raw_path!r}")
    effective_run_dir = Path(raw_path)
    trial_root = trial_run_dir.resolve()
    effective_root = effective_run_dir.resolve()
    if not effective_root.is_relative_to(trial_root):
        raise ValueError(
            f"eval_effective_run_dir must stay under trial run_dir {trial_run_dir}, "
            f"got {effective_run_dir}"
        )
    if not effective_run_dir.is_dir():
        raise ValueError(f"eval_effective_run_dir does not exist: {effective_run_dir}")
    return effective_run_dir


def _write_live_eval_command_record(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _recover_eval_run_result_after_nonzero_checker_exit(
    kwargs: dict[str, Any],
    *,
    sample_run_dir: Path,
) -> dict[str, Any]:
    if not _is_recoverable_checker_eval_sample(kwargs):
        return {}
    return _load_json(sample_run_dir / "run_result.json")


def _is_open_ended_eval_sample(kwargs: dict[str, Any]) -> bool:
    sample: EvalSample | None = kwargs.get("eval_sample")
    return sample is not None and sample.intent == "open-ended"


def _is_recoverable_checker_eval_sample(kwargs: dict[str, Any]) -> bool:
    sample: EvalSample | None = kwargs.get("eval_sample")
    return sample is not None and sample.intent in {"open-ended", "cleanup"}


def _live_surface_run_is_terminal(
    run_dir: Path,
    *,
    allow_open_ended_checker_failure: bool = False,
) -> bool:
    status = _load_json(run_dir / "live_status.json")
    if not status:
        return False
    exit_status = status.get("exit_status")
    if exit_status == 0:
        return True
    if exit_status not in {None, 0}:
        if allow_open_ended_checker_failure and _is_checker_failure(status):
            return True
        _raise_for_terminal_live_status(run_dir, status)
    return False


def _is_checker_failure(status: dict[str, Any]) -> bool:
    reason = str(status.get("reason") or "").lower()
    return "cleanup checker exited with status" in reason


def _raise_for_terminal_live_status(run_dir: Path, status: dict[str, Any]) -> None:
    if not status:
        return
    exit_status = status.get("exit_status")
    if exit_status in {None, 0}:
        return
    reason = str(status.get("reason") or status.get("provider_reason") or "").strip()
    detail = f": {reason}" if reason else ""
    raise RuntimeError(
        f"live surface run reported failed status {exit_status} at {run_dir}{detail}"
    )
