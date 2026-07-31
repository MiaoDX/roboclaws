from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from roboclaws.household import planner_probe_runtime_diagnostics as probe_runtime
from roboclaws.household import planner_probe_sampler_contract as probe_sampler
from roboclaws.household import planner_probe_sampler_diagnostics
from roboclaws.household.planner_probe_values import diagnostic_json_value
from roboclaws.household.planner_probe_worker_diagnostics import (
    _emit_worker_event,
    _record_cuda_memory_snapshot,
    _record_worker_exception_context,
)


def _prepare_execute_renderer(renderer_device_id: int | None) -> dict[str, Any]:
    _emit_worker_event("execute_renderer_adapter_start", stage="execute_renderer_adapter")
    renderer_adapter = probe_runtime.apply_headless_renderer_adapter(renderer_device_id)
    _emit_worker_event(
        "execute_renderer_adapter_ready",
        stage="execute_renderer_adapter",
        renderer_adapter=renderer_adapter,
    )
    return renderer_adapter


def _prepare_execute_task_sampler(
    config: Any,
    output_dir: Path,
    *,
    requested_cleanup_binding: dict[str, Any],
    task_sampler_robot_placement_profile: dict[str, Any],
) -> dict[str, Any]:
    _emit_worker_event("execute_task_sampler_construct_start", stage="execute_task_sampler")
    task_sampler = config.task_sampler_config.task_sampler_class(config)
    cleanup_task_sampler_adapter = probe_sampler.apply_exact_cleanup_task_sampler_adapter(
        task_sampler,
        requested_cleanup_binding,
    )
    task_sampler_failure_diagnostics = (
        planner_probe_sampler_diagnostics.apply_task_sampler_failure_diagnostics_adapter(
            task_sampler,
            task_sampler_robot_placement_profile,
            output_dir=output_dir,
            record_exception_context=_record_worker_exception_context,
        )
    )
    _record_worker_exception_context(
        cleanup_task_sampler_adapter=cleanup_task_sampler_adapter,
        requested_cleanup_primitive_binding=requested_cleanup_binding,
        task_sampler_robot_placement_profile=task_sampler_robot_placement_profile,
        task_sampler_failure_diagnostics=task_sampler_failure_diagnostics,
    )
    _emit_worker_event("execute_task_sampler_construct_done", stage="execute_task_sampler")
    return {
        "task_sampler": task_sampler,
        "cleanup_task_sampler_adapter": cleanup_task_sampler_adapter,
        "task_sampler_failure_diagnostics": task_sampler_failure_diagnostics,
    }


def _sample_execute_task(
    task_sampler: Any,
    requested_cleanup_binding: dict[str, Any],
) -> tuple[Any, dict[str, Any]]:
    _emit_worker_event("execute_task_sampler_reset_start", stage="execute_task_sampler_reset")
    task_sampler.reset()
    _emit_worker_event("execute_task_sampler_reset_done", stage="execute_task_sampler_reset")
    _emit_worker_event("execute_task_sample_start", stage="execute_task_sample")
    sample_variant = "base" if requested_cleanup_binding.get("scene_xml") else "ceiling"
    task = task_sampler.sample_task(variant=sample_variant)
    sampled_task_binding = probe_sampler.sampled_task_binding(task)
    cleanup_binding_result = probe_sampler.cleanup_primitive_binding_from_sampled_task(
        requested_cleanup_binding,
        sampled_task_binding,
    )
    _record_worker_exception_context(
        sampled_task_binding=sampled_task_binding,
        cleanup_primitive_binding=cleanup_binding_result.get("cleanup_primitive_binding"),
        cleanup_primitive_binding_blockers=cleanup_binding_result.get("blockers", []),
    )
    _emit_worker_event(
        "execute_task_sample_done",
        stage="execute_task_sample",
        sampled_task_binding=sampled_task_binding,
        requested_cleanup_primitive_binding=requested_cleanup_binding,
        cleanup_primitive_binding=cleanup_binding_result.get("cleanup_primitive_binding"),
        cleanup_primitive_binding_blockers=cleanup_binding_result.get("blockers", []),
    )
    _emit_worker_event("execute_task_reset_start", stage="execute_task_reset")
    task.reset()
    _emit_worker_event("execute_task_reset_done", stage="execute_task_reset")
    return task, {
        "sampled_task_binding": sampled_task_binding,
        "cleanup_binding_result": cleanup_binding_result,
    }


def _run_execute_policy(
    config: Any,
    task: Any,
    steps: int,
    run_task_for_steps_with_observations: Any,
) -> tuple[Any, Any, Any, dict[str, Any], dict[str, Any]]:
    _record_cuda_memory_snapshot("execute_policy_construct_before")
    _emit_worker_event("execute_policy_construct_start", stage="execute_policy_construct")
    policy = config.policy_config.policy_cls(config, task)
    _record_cuda_memory_snapshot("execute_policy_construct_after")
    _emit_worker_event("execute_policy_construct_done", stage="execute_policy_construct")
    _record_cuda_memory_snapshot("execute_policy_reset_before")
    _emit_worker_event("execute_policy_reset_start", stage="execute_policy_reset")
    policy.reset()
    _record_cuda_memory_snapshot("execute_policy_reset_after")
    _emit_worker_event("execute_policy_reset_done", stage="execute_policy_reset")
    _record_cuda_memory_snapshot("execute_policy_run_start")
    _emit_worker_event("execute_policy_run_start", stage="execute_policy_run", steps=steps)
    try:
        initial_qpos, final_qpos, initial_obs, final_obs = run_task_for_steps_with_observations(
            task,
            policy,
            num_steps=steps,
            profiler=None,
        )
    except BaseException as exc:  # noqa: BLE001 - preserve target-runtime diagnosis.
        _record_policy_run_exception(policy, exc, steps=steps)
        raise
    _record_cuda_memory_snapshot("execute_policy_run_done")
    _emit_worker_event("execute_policy_run_done", stage="execute_policy_run", steps=steps)
    return policy, initial_qpos, final_qpos, initial_obs, final_obs


def _record_policy_run_exception(policy: Any, exc: BaseException, *, steps: int) -> None:
    policy_exception_context = _policy_exception_context(
        policy,
        exc,
        stage="execute_policy_run",
        steps_requested=steps,
    )
    _record_worker_exception_context(
        policy_exception_context=policy_exception_context,
    )
    _emit_worker_event(
        "execute_policy_run_exception",
        stage="execute_policy_run",
        policy_exception_context=policy_exception_context,
    )
    _record_cuda_memory_snapshot("execute_policy_run_exception")


def _execute_probe_image_artifacts(
    output_dir: Path,
    initial_obs: dict[str, Any],
    final_obs: dict[str, Any],
) -> dict[str, str]:
    views_dir = output_dir / "planner_views"
    image_artifacts = {}
    initial = _write_first_camera_image(initial_obs, views_dir, "initial")
    final = _write_first_camera_image(final_obs, views_dir, "final")
    if initial:
        image_artifacts["initial"] = str(initial.relative_to(output_dir))
    if final:
        image_artifacts["final"] = str(final.relative_to(output_dir))
    return image_artifacts


def _policy_exception_context(
    policy: Any,
    exc: BaseException,
    *,
    stage: str,
    steps_requested: int,
) -> dict[str, Any]:
    action_primitives = [
        _policy_action_primitive_context(index, primitive)
        for index, primitive in enumerate(getattr(policy, "action_primitives", []) or [])
    ]
    return {
        "schema": "planner_probe_policy_exception_context_v1",
        "stage": stage,
        "steps_requested": steps_requested,
        "exception_type": type(exc).__name__,
        "message": str(exc),
        "failure_kind": _policy_exception_failure_kind(exc),
        "no_planned_trajectory": _policy_exception_is_no_planned_trajectory(exc),
        "policy_class": type(policy).__name__,
        "policy_module": type(policy).__module__,
        "policy_current_phase": _safe_current_phase(policy),
        "action_primitive_count": len(action_primitives),
        "action_primitives": action_primitives,
    }


def _policy_exception_failure_kind(exc: BaseException) -> str:
    if _policy_exception_is_no_planned_trajectory(exc):
        return "curobo_no_planned_trajectory"
    return "policy_exception"


def _policy_exception_is_no_planned_trajectory(exc: BaseException) -> bool:
    message = str(exc).lower()
    return "no planned trajectory" in message or "trajectory index >= len" in message


def _policy_action_primitive_context(index: int, primitive: Any) -> dict[str, Any]:
    trajectory = _safe_attr(primitive, "planned_trajectory")
    if trajectory is None:
        trajectory = _safe_attr(primitive, "_planned_trajectory")
    return {
        "index": index,
        "primitive_class": type(primitive).__name__,
        "primitive_module": type(primitive).__module__,
        "current_phase": _safe_current_phase(primitive),
        "planned_trajectory_present": trajectory is not None,
        "planned_trajectory_len": _safe_len(trajectory),
        "trajectory_index": diagnostic_json_value(
            _first_present_attr(
                primitive,
                (
                    "trajectory_index",
                    "_trajectory_index",
                    "current_trajectory_index",
                    "_current_trajectory_index",
                ),
            )
        ),
    }


def _safe_current_phase(obj: Any) -> str:
    getter = getattr(obj, "get_current_phase", None)
    if callable(getter):
        try:
            return str(getter())
        except Exception as exc:  # pragma: no cover - diagnostic only
            return f"{type(exc).__name__}: {exc}"
    for attr in ("current_phase", "phase"):
        value = _safe_attr(obj, attr)
        if value is not None:
            return str(value)
    return ""


def _first_present_attr(obj: Any, names: tuple[str, ...]) -> Any:
    for name in names:
        value = _safe_attr(obj, name)
        if value is not None:
            return value
    return None


def _safe_attr(obj: Any, name: str) -> Any:
    try:
        return getattr(obj, name)
    except Exception:  # pragma: no cover - diagnostic only
        return None


def _safe_len(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return len(value)
    except TypeError:
        return None


def _write_first_camera_image(
    obs_dict: dict[str, Any], output_dir: Path, prefix: str
) -> Path | None:
    import numpy as np
    from PIL import Image

    output_dir.mkdir(parents=True, exist_ok=True)
    for sensor_name, value in obs_dict.items():
        if "camera" not in sensor_name or "sensor_param" in sensor_name:
            continue
        if not isinstance(value, np.ndarray) or value.ndim != 3 or value.shape[2] != 3:
            continue
        image = Image.fromarray(np.clip(value, 0, 255).astype("uint8"))
        path = output_dir / f"{prefix}_{sensor_name}.png"
        image.save(path)
        return path
    return None


def _append_optional_int_arg(command: list[str], name: str, value: int | None) -> None:
    if value is not None:
        command.extend([name, str(value)])


def _append_optional_str_arg(command: list[str], name: str, value: str | None) -> None:
    if value:
        command.extend([name, str(value)])


def _prepend_pythonpath(path: Path, existing: str | None) -> str:
    value = str(path)
    if existing:
        return value + os.pathsep + existing
    return value
