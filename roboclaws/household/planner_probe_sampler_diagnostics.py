from __future__ import annotations

import sys
import time
from pathlib import Path
from types import MethodType
from typing import Any, Callable

from roboclaws.household.planner_probe_sampler_views import (
    _candidate_name_present,
    _candidate_object_count,
    _candidate_object_names,
    _capture_task_sampler_diagnostic_views,
    _grasp_failure_count,
    _install_place_robot_near_profile_adapter,
    _refresh_task_sampler_failure_diagnostics,
    _task_sampler_robot_placement_attempt,
    _task_sampler_robot_placement_config,
)
from roboclaws.household.planner_probe_values import diagnostic_json_value


def apply_task_sampler_failure_diagnostics_adapter(
    task_sampler: Any,
    robot_placement_profile: dict[str, Any] | None = None,
    *,
    output_dir: Path | None = None,
    record_exception_context: Callable[..., None] | None = None,
) -> dict[str, Any]:
    profile = robot_placement_profile or {}
    diagnostics: dict[str, Any] = {
        "schema": "planner_probe_task_sampler_failure_diagnostics_v1",
        "applied": False,
        "task_sampler_class": type(task_sampler).__name__,
        "robot_placement_config": _task_sampler_robot_placement_config(task_sampler),
        "robot_placement_profile": {
            "profile": profile.get("profile", "none"),
            "applied": bool(profile.get("applied")),
        },
        "place_robot_near_overrides": dict(profile.get("place_robot_near_overrides") or {}),
        "hooks": [],
        "robot_placement_attempts": [],
        "place_robot_near_calls": [],
        "placement_scene_diagnostics": [],
        "asset_failures": [],
        "grasp_load_attempts": [],
        "grasp_collision_checks": [],
        "grasp_failures": [],
        "candidate_removals": [],
        "candidate_removal_effectiveness": [],
        "image_artifacts": {},
        "visual_capture_failures": [],
    }
    _install_robot_placement_diagnostics(
        task_sampler,
        diagnostics,
        profile,
        output_dir=output_dir,
        record_exception_context=record_exception_context,
    )
    _install_asset_failure_diagnostics(task_sampler, diagnostics)
    _install_grasp_collision_diagnostics(task_sampler, diagnostics)
    _install_grasp_failure_diagnostics(task_sampler, diagnostics)
    _install_candidate_removal_diagnostics(task_sampler, diagnostics)
    diagnostics["applied"] = bool(diagnostics["hooks"])
    _refresh_task_sampler_failure_diagnostics(diagnostics)
    return diagnostics


def _install_robot_placement_diagnostics(
    task_sampler: Any,
    diagnostics: dict[str, Any],
    profile: dict[str, Any],
    *,
    output_dir: Path | None,
    record_exception_context: Callable[..., None] | None,
) -> None:
    sample_and_place_robot = getattr(task_sampler, "_sample_and_place_robot", None)
    if callable(sample_and_place_robot):

        def recording_sample_and_place_robot(self: Any, env: Any) -> Any:
            attempt = _task_sampler_robot_placement_attempt(self, env, diagnostics)
            started_at = time.monotonic()
            restore_place_robot_near = _install_place_robot_near_profile_adapter(
                env,
                diagnostics,
                profile,
            )
            try:
                result = sample_and_place_robot(env)
            except BaseException as exc:  # noqa: BLE001 - diagnostic wrapper must re-raise.
                attempt.update(
                    {
                        "result": "failed",
                        "exception_type": type(exc).__name__,
                        "message": str(exc),
                    }
                )
                raise
            else:
                attempt["result"] = "placed"
                image_artifacts = _capture_task_sampler_diagnostic_views(
                    env,
                    output_dir,
                    prefix=f"post_placement_attempt_{attempt['attempt_index']:03d}",
                    diagnostics=diagnostics,
                )
                if image_artifacts:
                    attempt["image_artifacts"] = image_artifacts
                    diagnostics["image_artifacts"].update(image_artifacts)
                    if record_exception_context is not None:
                        record_exception_context(image_artifacts=diagnostics["image_artifacts"])
                return result
            finally:
                restore_place_robot_near()
                attempt["elapsed_s"] = round(time.monotonic() - started_at, 6)
                diagnostics["robot_placement_attempts"].append(attempt)
                _refresh_task_sampler_failure_diagnostics(diagnostics)

        task_sampler._sample_and_place_robot = MethodType(  # noqa: SLF001
            recording_sample_and_place_robot,
            task_sampler,
        )
        diagnostics["hooks"].append("_sample_and_place_robot")


def _install_asset_failure_diagnostics(
    task_sampler: Any,
    diagnostics: dict[str, Any],
) -> None:
    report_asset_failure = getattr(task_sampler, "report_asset_failure", None)
    if callable(report_asset_failure):

        def recording_report_asset_failure(self: Any, asset_uid: Any, reason: Any) -> Any:
            diagnostics["asset_failures"].append(
                {
                    "asset_uid": str(asset_uid or ""),
                    "reason": str(reason or ""),
                }
            )
            _refresh_task_sampler_failure_diagnostics(diagnostics)
            return report_asset_failure(asset_uid, reason)

        task_sampler.report_asset_failure = MethodType(  # noqa: SLF001
            recording_report_asset_failure,
            task_sampler,
        )
        diagnostics["hooks"].append("report_asset_failure")


def _install_grasp_failure_diagnostics(
    task_sampler: Any,
    diagnostics: dict[str, Any],
) -> None:
    report_grasp_failure = getattr(task_sampler, "report_grasp_failure", None)
    if callable(report_grasp_failure):

        def recording_report_grasp_failure(
            self: Any,
            obj_name: Any,
            max_failures: int = 2,
        ) -> Any:
            before_candidates = _candidate_object_count(self)
            before_count = _grasp_failure_count(self, obj_name)
            before_names = _candidate_object_names(self)
            removal_count_before = len(diagnostics.get("candidate_removals") or [])
            result = report_grasp_failure(obj_name, max_failures)
            after_candidates = _candidate_object_count(self)
            after_count = _grasp_failure_count(self, obj_name)
            after_names = _candidate_object_names(self)
            removal_count_after = len(diagnostics.get("candidate_removals") or [])
            diagnostics["grasp_failures"].append(
                {
                    "object_name": str(obj_name or ""),
                    "count_before": before_count,
                    "count_after": after_count,
                    "max_failures": int(max_failures),
                    "threshold_exceeded": after_count > int(max_failures),
                    "threshold_crossed": before_count <= int(max_failures) < after_count,
                    "candidate_count_before": before_candidates,
                    "candidate_count_after": after_candidates,
                    "candidate_name_present_before": _candidate_name_present(
                        before_names,
                        obj_name,
                    ),
                    "candidate_name_present_after": _candidate_name_present(after_names, obj_name),
                    "candidate_removal_call_count_before": removal_count_before,
                    "candidate_removal_call_count_after": removal_count_after,
                    "candidate_removal_call_count_delta": (
                        removal_count_after - removal_count_before
                    ),
                    "removed_candidate": (
                        before_candidates is not None
                        and after_candidates is not None
                        and after_candidates < before_candidates
                    ),
                }
            )
            _refresh_task_sampler_failure_diagnostics(diagnostics)
            return result

        task_sampler.report_grasp_failure = MethodType(  # noqa: SLF001
            recording_report_grasp_failure,
            task_sampler,
        )
        diagnostics["hooks"].append("report_grasp_failure")


def _install_candidate_removal_diagnostics(
    task_sampler: Any,
    diagnostics: dict[str, Any],
) -> None:
    remove_candidate_object = getattr(task_sampler, "_remove_candidate_object", None)
    if callable(remove_candidate_object):

        def recording_remove_candidate_object(self: Any, object_name: Any) -> Any:
            before_candidates = _candidate_object_count(self)
            before_names = _candidate_object_names(self)
            result = remove_candidate_object(object_name)
            after_candidates = _candidate_object_count(self)
            after_names = _candidate_object_names(self)
            record = {
                "object_name": str(object_name or ""),
                "candidate_count_before": before_candidates,
                "candidate_count_after": after_candidates,
                "candidate_name_present_before": _candidate_name_present(
                    before_names,
                    object_name,
                ),
                "candidate_name_present_after": _candidate_name_present(after_names, object_name),
                "effective_removal": (
                    before_candidates is not None
                    and after_candidates is not None
                    and after_candidates < before_candidates
                ),
                "candidate_names_before": before_names,
                "candidate_names_after": after_names,
            }
            diagnostics["candidate_removals"].append(record)
            diagnostics["candidate_removal_effectiveness"].append(record)
            _refresh_task_sampler_failure_diagnostics(diagnostics)
            return result

        task_sampler._remove_candidate_object = MethodType(  # noqa: SLF001
            recording_remove_candidate_object,
            task_sampler,
        )
        diagnostics["hooks"].append("_remove_candidate_object")


def _install_grasp_collision_diagnostics(task_sampler: Any, diagnostics: dict[str, Any]) -> None:
    installed_hooks = []
    for module in _task_sampler_grasp_modules(task_sampler):
        for hook_name in (
            _install_grasp_load_diagnostic_hook(module, task_sampler, diagnostics),
            _install_grasp_mask_diagnostic_hook(module, task_sampler, diagnostics),
        ):
            if hook_name:
                installed_hooks.append(hook_name)

    if installed_hooks:
        diagnostics["hooks"].append("grasp_collision_diagnostics")
        diagnostics["grasp_collision_hooks"] = installed_hooks


def _install_grasp_load_diagnostic_hook(
    module: Any,
    task_sampler: Any,
    diagnostics: dict[str, Any],
) -> str | None:
    load_grasps_for_object = getattr(module, "load_grasps_for_object", None)
    if not callable(load_grasps_for_object):
        return None
    original_load = getattr(
        load_grasps_for_object,
        "__roboclaws_original__",
        load_grasps_for_object,
    )
    module_name = str(getattr(module, "__name__", ""))

    def recording_load_grasps_for_object(
        object_name: Any,
        num_grasps: int = 50,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        record: dict[str, Any] = {
            "schema": "planner_probe_grasp_load_attempt_v1",
            "module": module_name,
            "asset_uid": str(object_name or ""),
            "pickup_obj_name": _task_sampler_config_pickup_obj_name(task_sampler),
            "requested_grasp_count": _safe_count_value(num_grasps),
        }
        started_at = time.monotonic()
        try:
            result = original_load(object_name, num_grasps, *args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - diagnostic wrapper must re-raise.
            record.update(
                {
                    "result": "exception",
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
            raise
        else:
            gripper, cached_grasps = result
            record.update(
                {
                    "result": "loaded",
                    "gripper": str(gripper or ""),
                    "cached_grasp_count": _safe_len(cached_grasps),
                }
            )
            return result
        finally:
            record["elapsed_s"] = round(time.monotonic() - started_at, 6)
            diagnostics["grasp_load_attempts"].append(record)
            _refresh_task_sampler_failure_diagnostics(diagnostics)

    recording_load_grasps_for_object.__roboclaws_original__ = original_load  # type: ignore[attr-defined]
    setattr(module, "load_grasps_for_object", recording_load_grasps_for_object)
    return f"{module_name}.load_grasps_for_object"


def _install_grasp_mask_diagnostic_hook(
    module: Any,
    task_sampler: Any,
    diagnostics: dict[str, Any],
) -> str | None:
    get_noncolliding_grasp_mask = getattr(module, "get_noncolliding_grasp_mask", None)
    if not callable(get_noncolliding_grasp_mask):
        return None
    original_mask = getattr(
        get_noncolliding_grasp_mask,
        "__roboclaws_original__",
        get_noncolliding_grasp_mask,
    )
    module_name = str(getattr(module, "__name__", ""))

    def recording_get_noncolliding_grasp_mask(
        mj_model: Any,
        mj_data: Any,
        grasp_poses_world: Any,
        batch_size: int,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        record = {
            "schema": "planner_probe_grasp_collision_check_v1",
            "module": module_name,
            "asset_uid": _latest_grasp_load_asset_uid(diagnostics),
            "pickup_obj_name": _task_sampler_config_pickup_obj_name(task_sampler),
            "grasp_pose_count": _safe_len(grasp_poses_world),
            "batch_size": _safe_count_value(batch_size),
        }
        started_at = time.monotonic()
        try:
            result = original_mask(
                mj_model,
                mj_data,
                grasp_poses_world,
                batch_size,
                *args,
                **kwargs,
            )
        except BaseException as exc:  # noqa: BLE001 - diagnostic wrapper must re-raise.
            record.update(
                {
                    "result": "exception",
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
            raise
        else:
            noncolliding_count = _truthy_count(result)
            grasp_pose_count = _safe_len(grasp_poses_world)
            record.update(
                {
                    "result": "checked",
                    "noncolliding_grasp_count": noncolliding_count,
                    "colliding_grasp_count": (
                        grasp_pose_count - noncolliding_count
                        if grasp_pose_count is not None and noncolliding_count is not None
                        else None
                    ),
                    "zero_noncolliding": noncolliding_count == 0,
                }
            )
            return result
        finally:
            record["elapsed_s"] = round(time.monotonic() - started_at, 6)
            diagnostics["grasp_collision_checks"].append(record)
            _refresh_task_sampler_failure_diagnostics(diagnostics)

    recording_get_noncolliding_grasp_mask.__roboclaws_original__ = original_mask  # type: ignore[attr-defined]
    setattr(module, "get_noncolliding_grasp_mask", recording_get_noncolliding_grasp_mask)
    return f"{module_name}.get_noncolliding_grasp_mask"


def _task_sampler_grasp_modules(task_sampler: Any) -> list[Any]:
    modules: list[Any] = []
    module_names = {"molmo_spaces.tasks.pick_task_sampler"}
    for method_name in ("_sample_task", "sample", "next_task"):
        method = getattr(task_sampler, method_name, None)
        module_name = getattr(method, "__module__", None)
        if module_name:
            module_names.add(str(module_name))
    for module_name in sorted(module_names):
        module = sys.modules.get(module_name)
        if module is None:
            continue
        if module not in modules and (
            hasattr(module, "load_grasps_for_object")
            or hasattr(module, "get_noncolliding_grasp_mask")
        ):
            modules.append(module)
    return modules


def _task_sampler_config_pickup_obj_name(task_sampler: Any) -> str:
    task_config = getattr(getattr(task_sampler, "config", None), "task_config", None)
    return str(getattr(task_config, "pickup_obj_name", "") or "")


def _latest_grasp_load_asset_uid(diagnostics: dict[str, Any]) -> str:
    for item in reversed(diagnostics.get("grasp_load_attempts") or []):
        if isinstance(item, dict) and item.get("asset_uid"):
            return str(item.get("asset_uid") or "")
    return ""


def _safe_len(value: Any) -> int | None:
    try:
        return len(value)
    except TypeError:
        return None


def _safe_count_value(value: Any) -> Any:
    try:
        return int(value)
    except Exception:
        return diagnostic_json_value(value)


def _truthy_count(value: Any) -> int | None:
    try:
        import numpy as np

        return int(np.sum(value))
    except Exception:
        pass
    try:
        return sum(1 for item in value if bool(item))
    except TypeError:
        return None
