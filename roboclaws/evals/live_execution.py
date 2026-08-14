"""Live eval trial orchestration and product-process execution."""

from __future__ import annotations

import os
import signal
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from roboclaws.evals.dependencies import dependency_failure, resolve_artifact_dependencies
from roboclaws.evals.live_artifacts import (
    discover_live_surface_run_dir,
)
from roboclaws.evals.live_retry import (
    LIVE_TRIAL_ATTEMPTS_FILENAME,
    run_with_model_call_stall_retry,
)
from roboclaws.evals.live_runtime import (
    _live_eval_effective_run_dir,
    _live_surface_already_complete,
    _load_json,
    _subprocess_text_output,
    _write_live_eval_command_record,
    live_product_run_kwargs,
    live_stall_timeout_s,
    live_surface_command,
    live_surface_env,
    live_surface_run_dir,
    live_timeout_completion_grace_s,
    live_wall_clock_budget_s,
    wait_for_live_surface_completion,
    wait_for_timed_out_live_surface_artifact,
)
from roboclaws.evals.live_timeout import (
    LiveEvalTimeoutError,
    cleanup_timed_out_live_children,
    live_timeout_snapshot,
)
from roboclaws.evals.models import (
    MISSING_UNAVAILABLE,
    EvalResult,
    EvalSample,
    EvalTrial,
)
from roboclaws.launch.catalog import resolve_surface_launch
from roboclaws.launch.executor import LaunchProcess, spawn_launch_plan
from roboclaws.launch.plans import LaunchPlan
from roboclaws.mcp.endpoint import EVAL_HARNESS_MCP_PORT_ENV, free_mcp_port

REPO_ROOT = Path(__file__).resolve().parents[2]
ProductRun = Callable[..., dict[str, Any]]
DEFAULT_LIVE_WALL_CLOCK_BUDGET_S = 1200.0
DEFAULT_LIVE_STALL_TIMEOUT_S = 120.0
DEFAULT_LIVE_TIMEOUT_COMPLETION_GRACE_S = 30.0
LIVE_PROCESS_POLL_S = 1.0


@dataclass(frozen=True)
class LiveSurfaceProcessResult:
    returncode: int | str
    stdout: str
    stderr: str
    timeout_kind: str | None = None
    wall_clock_budget_s: float | None = None
    stall_timeout_s: float | None = None
    elapsed_s: float = 0.0
    last_progress_elapsed_s: float = 0.0


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
    runtime_map_prior: Path | None,
    agent_engine: str,
    provider_profile: str,
    model: str | None,
    live_timeout_s: float | None,
    live_stall_timeout_s: float | None,
    skill_delivery_cell: str = "static-full",
    live_product_runner: ProductRun,
    hooks: LiveTrialHooks,
    skill_source_root: Path | None = None,
    live_retry_limit: int = 1,
) -> EvalResult:
    """Run and grade one live-agent eval trial through the product surface."""

    try:
        dependency_artifacts = resolve_artifact_dependencies(
            sample,
            repetition_index=repetition_index,
            sample_artifacts=sample_artifacts,
            runtime_map_prior=runtime_map_prior,
        )
        failure = dependency_failure(dependency_artifacts)
        if failure is not None:
            return hooks.failed_result_from_dependency(trial, run_dir, failure)

        def run_attempt(attempt_run_dir: Path) -> tuple[dict[str, Any], Path]:
            result = live_product_runner(
                **live_product_run_kwargs(
                    sample,
                    run_dir=attempt_run_dir,
                    budget=budget,
                    dependency_artifacts=dependency_artifacts,
                    agent_engine=agent_engine,
                    provider_profile=provider_profile,
                    model=model,
                    live_timeout_s=live_timeout_s,
                    live_stall_timeout_s=live_stall_timeout_s,
                    skill_delivery_cell=skill_delivery_cell,
                    model_visible_tool_surface=trial.tool_surface,
                    skill_source_root=skill_source_root,
                )
            )
            return result, _live_eval_effective_run_dir(result, trial_run_dir=attempt_run_dir)

        run_result, effective_run_dir = run_with_model_call_stall_retry(
            run_dir=run_dir,
            run_attempt=run_attempt,
            max_retries=live_retry_limit,
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
    delivery_artifact = effective_run_dir / "openai-agents-skill-context.json"
    if delivery_artifact.is_file():
        artifacts["openai_agents_skill_context"] = str(delivery_artifact)
    attempts_path = run_dir / LIVE_TRIAL_ATTEMPTS_FILENAME
    if attempts_path.is_file():
        artifacts["live_trial_attempts"] = str(attempts_path)
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
    env = live_surface_env(kwargs, base_env=os.environ)
    port = str(kwargs.get("port") or env.get(EVAL_HARNESS_MCP_PORT_ENV) or free_mcp_port())
    command = live_surface_command({**kwargs, "port": port}, output_dir=sample_run_root)
    plan = resolve_surface_launch(command[5:])
    wall_clock_budget_s = live_wall_clock_budget_s(kwargs)
    stall_timeout_s = live_stall_timeout_s(kwargs)
    started_wall_time_s = time.time()
    started = time.monotonic()
    record: dict[str, Any] = {
        "command": command,
        "returncode": None,
        "stdout": "",
        "stderr": "",
        "effective_run_dir": str(sample_run_dir),
        "wall_clock_budget_s": wall_clock_budget_s,
        "stall_timeout_s": stall_timeout_s,
    }
    completed = _run_live_surface_foreground_process(
        plan=plan,
        env=env,
        kwargs=kwargs,
        output_dir=sample_run_root,
        fallback_run_dir=sample_run_dir,
        started_wall_time_s=started_wall_time_s,
        wall_clock_budget_s=wall_clock_budget_s,
        stall_timeout_s=stall_timeout_s,
    )
    if completed.timeout_kind is not None:
        sample_run_dir = discover_live_surface_run_dir(
            kwargs,
            output_dir=sample_run_root,
            fallback_run_dir=sample_run_dir,
            stdout=completed.stdout,
            started_wall_time_s=started_wall_time_s,
        )
        sample_run_dir = wait_for_timed_out_live_surface_artifact(
            kwargs,
            output_dir=sample_run_root,
            effective_run_dir=sample_run_dir,
            started_wall_time_s=started_wall_time_s,
        )
        record.update(
            {
                "returncode": completed.returncode,
                "stdout": completed.stdout,
                "stderr": completed.stderr,
                "timeout_kind": completed.timeout_kind,
                "timeout_s": wall_clock_budget_s,
                "wall_clock_budget_s": wall_clock_budget_s,
                "stall_timeout_s": stall_timeout_s,
                "timeout_elapsed_s": completed.elapsed_s,
                "timeout_last_progress_elapsed_s": completed.last_progress_elapsed_s,
                "timeout_completion_grace_s": live_timeout_completion_grace_s(),
                "effective_run_dir": str(sample_run_dir),
                "live_status": _load_json(sample_run_dir / "live_status.json"),
            }
        )
        record["timeout_debug_snapshot"] = live_timeout_snapshot(
            sample_run_dir,
            live_status=record["live_status"],
            timeout_s=wall_clock_budget_s,
            timeout_kind=completed.timeout_kind,
            wall_clock_budget_s=wall_clock_budget_s,
            stall_timeout_s=stall_timeout_s,
        )
        run_result_path = sample_run_dir / "run_result.json"
        run_result = _load_json(run_result_path)
        if run_result and _live_surface_already_complete(
            sample_run_dir,
            require_terminal_status=False,
        ):
            record["returncode"] = "timeout_after_completion"
            _write_live_eval_command_record(run_dir / "live_eval_command.json", record)
            run_result["eval_effective_run_dir"] = str(sample_run_dir)
            return run_result
        record["timeout_child_cleanup"] = cleanup_timed_out_live_children(sample_run_dir)
        _write_live_eval_command_record(run_dir / "live_eval_command.json", record)
        message = _live_timeout_message(
            timeout_kind=completed.timeout_kind,
            wall_clock_budget_s=wall_clock_budget_s,
            stall_timeout_s=stall_timeout_s,
        )
        raise LiveEvalTimeoutError(
            message,
            timeout_s=wall_clock_budget_s,
            timeout_kind=completed.timeout_kind,
            wall_clock_budget_s=wall_clock_budget_s,
            stall_timeout_s=stall_timeout_s,
            effective_run_dir=sample_run_dir,
            live_status=record["live_status"],
            timeout_debug_snapshot=record["timeout_debug_snapshot"],
            command_record=record,
        )

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
        message = completed.stderr.strip() or completed.stdout.strip()
        raise RuntimeError(f"live surface run failed with exit {completed.returncode}: {message}")
    sample_run_dir = wait_for_live_surface_completion(
        kwargs,
        output_dir=sample_run_root,
        effective_run_dir=sample_run_dir,
        elapsed_s=time.monotonic() - started,
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


def _run_live_surface_foreground_process(
    *,
    plan: LaunchPlan,
    env: dict[str, str],
    kwargs: dict[str, Any],
    output_dir: Path,
    fallback_run_dir: Path,
    started_wall_time_s: float,
    wall_clock_budget_s: float,
    stall_timeout_s: float,
) -> LiveSurfaceProcessResult:
    started = time.monotonic()
    last_progress_at = started
    last_progress_signature: tuple[Any, ...] | None = None
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stdout_file:
        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stderr_file:
            process = spawn_launch_plan(
                plan,
                cwd=REPO_ROOT,
                env=env,
                stdout=stdout_file,
                stderr=stderr_file,
            )
            while True:
                now = time.monotonic()
                elapsed_s = max(now - started, 0.0)
                stdout_text = _temporary_file_text(stdout_file)
                effective_run_dir = _live_surface_run_dir_for_monitor(
                    kwargs,
                    output_dir=output_dir,
                    fallback_run_dir=fallback_run_dir,
                    stdout=stdout_text,
                    started_wall_time_s=started_wall_time_s,
                )
                progress_signature = _live_surface_progress_signature(effective_run_dir)
                if last_progress_signature is None:
                    last_progress_signature = progress_signature
                elif progress_signature != last_progress_signature:
                    last_progress_signature = progress_signature
                    last_progress_at = now

                returncode = process.poll()
                if returncode is not None:
                    return LiveSurfaceProcessResult(
                        returncode=returncode,
                        stdout=_temporary_file_text(stdout_file),
                        stderr=_temporary_file_text(stderr_file),
                        wall_clock_budget_s=wall_clock_budget_s,
                        stall_timeout_s=stall_timeout_s,
                        elapsed_s=elapsed_s,
                        last_progress_elapsed_s=max(last_progress_at - started, 0.0),
                    )
                if elapsed_s >= wall_clock_budget_s:
                    _terminate_live_surface_process(process)
                    return LiveSurfaceProcessResult(
                        returncode="wall_clock_budget_exhausted",
                        stdout=_temporary_file_text(stdout_file),
                        stderr=_temporary_file_text(stderr_file),
                        timeout_kind="wall_clock_budget_exhausted",
                        wall_clock_budget_s=wall_clock_budget_s,
                        stall_timeout_s=stall_timeout_s,
                        elapsed_s=elapsed_s,
                        last_progress_elapsed_s=max(last_progress_at - started, 0.0),
                    )
                stalled_s = max(now - last_progress_at, 0.0)
                if stalled_s >= stall_timeout_s:
                    _terminate_live_surface_process(process)
                    return LiveSurfaceProcessResult(
                        returncode="stall_timeout",
                        stdout=_temporary_file_text(stdout_file),
                        stderr=_temporary_file_text(stderr_file),
                        timeout_kind="stall_timeout",
                        wall_clock_budget_s=wall_clock_budget_s,
                        stall_timeout_s=stall_timeout_s,
                        elapsed_s=elapsed_s,
                        last_progress_elapsed_s=max(last_progress_at - started, 0.0),
                    )
                time.sleep(
                    min(
                        LIVE_PROCESS_POLL_S,
                        max(wall_clock_budget_s - elapsed_s, 0.0),
                        max(stall_timeout_s - stalled_s, 0.0),
                    )
                )


def _live_surface_run_dir_for_monitor(
    kwargs: dict[str, Any],
    *,
    output_dir: Path,
    fallback_run_dir: Path,
    stdout: str,
    started_wall_time_s: float,
) -> Path:
    try:
        return discover_live_surface_run_dir(
            kwargs,
            output_dir=output_dir,
            fallback_run_dir=fallback_run_dir,
            stdout=stdout,
            started_wall_time_s=started_wall_time_s,
        )
    except RuntimeError:
        return fallback_run_dir


def _live_surface_progress_signature(run_dir: Path) -> tuple[Any, ...]:
    status = _load_json_for_progress(run_dir / "live_status.json")
    snapshot = (
        status.get("debug_snapshot") if isinstance(status.get("debug_snapshot"), dict) else {}
    )
    progress = snapshot.get("progress") if isinstance(snapshot.get("progress"), dict) else {}
    tool_counts = (
        snapshot.get("tool_response_counts")
        if isinstance(snapshot.get("tool_response_counts"), dict)
        else {}
    )
    return (
        str(status.get("phase") or ""),
        status.get("exit_status"),
        _file_progress_signature(run_dir / "run_result.json"),
        _file_progress_signature(run_dir / "report.html"),
        _file_progress_signature(run_dir / "trace.jsonl"),
        _glob_progress_signature(run_dir, "openai-agents-events*.jsonl"),
        snapshot.get("run_result_present"),
        snapshot.get("report_present"),
        snapshot.get("trace_event_count"),
        snapshot.get("trace_request_count"),
        snapshot.get("trace_response_count"),
        snapshot.get("last_trace_event"),
        snapshot.get("last_trace_response"),
        snapshot.get("last_trace_wallclock_elapsed_s"),
        tuple(sorted((str(key), value) for key, value in progress.items())),
        tuple(sorted((str(key), value) for key, value in tool_counts.items())),
        snapshot.get("openai_agents_event_count"),
        snapshot.get("last_openai_agents_event"),
        snapshot.get("last_openai_agents_ts_epoch"),
        snapshot.get("model_service_attempt_count"),
        snapshot.get("model_service_success_count"),
        snapshot.get("model_service_failure_count"),
        snapshot.get("model_racing_arm_start_count"),
        snapshot.get("model_racing_arm_finish_count"),
    )


def _load_json_for_progress(path: Path) -> dict[str, Any]:
    try:
        return _load_json(path)
    except (OSError, ValueError):
        return {}


def _file_progress_signature(path: Path) -> tuple[bool, int, int]:
    try:
        stat = path.stat()
    except OSError:
        return (False, 0, 0)
    return (True, stat.st_size, stat.st_mtime_ns)


def _glob_progress_signature(run_dir: Path, pattern: str) -> tuple[tuple[str, bool, int, int], ...]:
    return tuple(
        (path.name, *_file_progress_signature(path))
        for path in sorted(run_dir.glob(pattern), key=lambda item: item.name)
    )


def _terminate_live_surface_process(process: LaunchProcess) -> None:
    if process.poll() is not None:
        return
    process_group_id = process.pid
    try:
        os.killpg(process_group_id, signal.SIGTERM)
    except OSError:
        return
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        pass
    # The `just` wrapper can exit before its product child; finish the whole group.
    try:
        os.killpg(process_group_id, signal.SIGKILL)
    except OSError:
        return
    try:
        process.wait(timeout=5.0)
    except subprocess.TimeoutExpired:
        return


def _temporary_file_text(file_obj: Any) -> str:
    try:
        file_obj.flush()
        position = file_obj.tell()
        file_obj.seek(0)
        text = file_obj.read()
        file_obj.seek(position)
    except OSError:
        return ""
    return _subprocess_text_output(text)


def _live_timeout_message(
    *,
    timeout_kind: str,
    wall_clock_budget_s: float,
    stall_timeout_s: float,
) -> str:
    if timeout_kind == "stall_timeout":
        return f"live eval trial stalled after {stall_timeout_s:g}s without progress"
    if timeout_kind == "wall_clock_budget_exhausted":
        return f"live eval trial exceeded wall-clock budget after {wall_clock_budget_s:g}s"
    return f"live eval trial timed out after {wall_clock_budget_s:g}s"
