from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from roboclaws.household.planner_probe_values import diagnostic_json_value


def _capture_task_sampler_diagnostic_views(
    env: Any,
    output_dir: Path | None,
    *,
    prefix: str,
    diagnostics: dict[str, Any],
) -> dict[str, str]:
    if output_dir is None or int(diagnostics.get("visual_capture_count") or 0) >= 1:
        return {}
    try:
        camera_manager = getattr(env, "camera_manager", None)
        registry = getattr(camera_manager, "registry", None)
        update_all = getattr(registry, "update_all_cameras", None)
        if callable(update_all):
            update_all(env)
        camera_names = _task_sampler_diagnostic_camera_names(env)
        if not camera_names:
            return {}
        views_dir = output_dir / "planner_views"
        artifacts = {}
        for camera_name in camera_names[:1]:
            path = _write_env_camera_image(env, camera_name, views_dir, prefix)
            if path:
                key = f"{prefix}_{_safe_artifact_key(camera_name)}"
                artifacts[key] = str(path.relative_to(output_dir))
        if artifacts:
            diagnostics["visual_capture_count"] = (
                int(diagnostics.get("visual_capture_count") or 0) + 1
            )
        return artifacts
    except Exception as exc:  # pragma: no cover - best-effort failure evidence.
        diagnostics.setdefault("visual_capture_failures", []).append(
            {
                "prefix": prefix,
                "exception_type": type(exc).__name__,
                "message": str(exc),
            }
        )
        return {}


def _task_sampler_diagnostic_camera_names(env: Any) -> list[str]:
    registry = getattr(getattr(env, "camera_manager", None), "registry", None)
    keys = getattr(registry, "keys", None)
    if not callable(keys):
        return []
    names = [str(name) for name in keys()]
    preferred = [
        "head_camera",
        "camera_follower",
        "wrist_camera",
        "wrist_camera_l",
        "wrist_camera_r",
        "exo_camera_1",
    ]
    ordered = [name for name in preferred if name in names]
    ordered.extend(name for name in names if name not in ordered)
    return ordered


def _write_env_camera_image(
    env: Any,
    camera_name: str,
    output_dir: Path,
    prefix: str,
) -> Path | None:
    import numpy as np
    from PIL import Image

    render = getattr(env, "render_rgb_frame", None)
    if not callable(render):
        return None
    frame = np.asarray(render(camera_name))
    if frame.ndim != 3:
        return None
    if frame.shape[2] > 3:
        frame = frame[:, :, :3]
    if frame.dtype.kind == "f" and float(np.nanmax(frame)) <= 1.0:
        frame = frame * 255.0
    image = Image.fromarray(np.clip(frame, 0, 255).astype("uint8"))
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{prefix}_{_safe_artifact_key(camera_name)}.png"
    image.save(path)
    return path


def _safe_artifact_key(value: str) -> str:
    cleaned = "".join(char if char.isalnum() else "_" for char in value.strip())
    return cleaned.strip("_") or "camera"


def _candidate_object_count(task_sampler: Any) -> int | None:
    candidate_objects = getattr(task_sampler, "candidate_objects", None)
    try:
        return len(candidate_objects) if candidate_objects is not None else None
    except TypeError:
        return None


def _candidate_object_names(task_sampler: Any, *, limit: int = 40) -> list[str] | None:
    candidate_objects = getattr(task_sampler, "candidate_objects", None)
    if candidate_objects is None:
        return None
    names = []
    try:
        iterator = iter(candidate_objects)
    except TypeError:
        return None
    for item in iterator:
        if len(names) >= limit:
            break
        name = getattr(item, "name", None)
        names.append(str(name if name is not None else item))
    return names


def _candidate_name_present(candidate_names: list[str] | None, object_name: Any) -> bool | None:
    if candidate_names is None:
        return None
    return str(object_name or "") in candidate_names


def _grasp_failure_count(task_sampler: Any, obj_name: Any) -> int:
    counts = getattr(task_sampler, "_grasp_failure_counts", None) or {}
    return int(counts.get(obj_name, 0))


def _install_place_robot_near_profile_adapter(
    env: Any,
    diagnostics: dict[str, Any],
    robot_placement_profile: dict[str, Any],
) -> Any:
    overrides = dict(robot_placement_profile.get("place_robot_near_overrides") or {})
    original = getattr(env, "place_robot_near", None)
    if not callable(original):
        return lambda: None
    should_apply_overrides = bool(overrides and robot_placement_profile.get("applied"))

    def profiled_place_robot_near(*args: Any, **kwargs: Any) -> Any:
        call = {
            "call_index": len(diagnostics.get("place_robot_near_calls") or []) + 1,
            "requested": _place_robot_near_call_values(kwargs),
        }
        effective_kwargs = dict(kwargs)
        if should_apply_overrides:
            for name, value in overrides.items():
                effective_kwargs[name] = value
        call["effective"] = _place_robot_near_call_values(effective_kwargs)
        scene_diagnostic = _place_robot_near_scene_diagnostic(
            env,
            call["call_index"],
            effective_kwargs,
        )
        if scene_diagnostic:
            call["scene_diagnostic"] = scene_diagnostic
            diagnostics["placement_scene_diagnostics"].append(scene_diagnostic)
        started_at = time.monotonic()
        try:
            result = original(*args, **effective_kwargs)
        except BaseException as exc:  # noqa: BLE001 - diagnostic wrapper must re-raise.
            call.update(
                {
                    "result": "exception",
                    "exception_type": type(exc).__name__,
                    "message": str(exc),
                }
            )
            raise
        else:
            call["result"] = diagnostic_json_value(result)
            return result
        finally:
            call["elapsed_s"] = round(time.monotonic() - started_at, 6)
            diagnostics["place_robot_near_calls"].append(call)
            _refresh_task_sampler_failure_diagnostics(diagnostics)

    setattr(env, "place_robot_near", profiled_place_robot_near)

    def restore() -> None:
        setattr(env, "place_robot_near", original)

    return restore


def _place_robot_near_scene_diagnostic(
    env: Any,
    call_index: int,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    diagnostic: dict[str, Any] = {
        "schema": "planner_probe_placement_scene_diagnostic_v1",
        "call_index": call_index,
        "target_name": _target_name(kwargs.get("target")),
        "sampling_radius_range": diagnostic_json_value(
            kwargs.get("sampling_radius_range", (0.0, 1.0))
        ),
        "robot_safety_radius": diagnostic_json_value(kwargs.get("robot_safety_radius")),
    }
    try:
        import numpy as np
    except Exception as exc:  # pragma: no cover - diagnostic only.
        diagnostic["error"] = f"{type(exc).__name__}: {exc}"
        return diagnostic

    target_position = _target_position(env, kwargs.get("target"))
    if target_position is None:
        diagnostic["error"] = "target_position_unavailable"
        return diagnostic
    target_position_array = np.asarray(target_position, dtype=float)
    diagnostic["target_position"] = diagnostic_json_value(target_position_array)
    radius_range = _radius_range(kwargs.get("sampling_radius_range", (0.0, 1.0)))
    if radius_range is None:
        diagnostic["error"] = "sampling_radius_range_unavailable"
        return diagnostic
    radius_min, radius_max = radius_range
    diagnostic["sampling_area_m2"] = round(
        float(np.pi * (radius_max**2 - radius_min**2)),
        6,
    )
    try:
        thormap = env.get_thormap(
            agent_radius=float(kwargs.get("robot_safety_radius") or 0.35),
            px_per_m=200,
        )
        free_points = thormap.get_free_points()
        diagnostic["px_per_m"] = diagnostic_json_value(getattr(thormap, "px_per_m", ""))
        diagnostic["total_free_point_count"] = int(len(free_points))
        if len(free_points) == 0:
            diagnostic["valid_free_point_count"] = 0
            diagnostic["valid_neighborhood_fraction"] = 0.0
            diagnostic["low_free_space"] = True
            return diagnostic
        target_dist = np.linalg.norm(free_points[:, :2] - target_position_array[:2], axis=1)
        valid_mask = (target_dist > radius_min) & (target_dist < radius_max)
        valid_count = int(valid_mask.sum())
        sq_m_per_sq_px = 1 / float(getattr(thormap, "px_per_m", 200) ** 2)
        area = np.pi * (radius_max**2 - radius_min**2)
        fraction = float(valid_count * sq_m_per_sq_px / area) if area > 0 else 0.0
        nearest_index = int(np.argmin(target_dist))
        diagnostic.update(
            {
                "valid_free_point_count": valid_count,
                "valid_neighborhood_fraction": round(fraction, 6),
                "low_free_space": fraction <= 0.05,
                "nearest_free_point_distance_m": round(float(target_dist[nearest_index]), 6),
                "nearest_free_point": diagnostic_json_value(free_points[nearest_index]),
                "radius_band_counts": _radius_band_counts(target_dist, radius_max),
            }
        )
    except Exception as exc:  # pragma: no cover - best-effort diagnostics.
        diagnostic["error"] = f"{type(exc).__name__}: {exc}"
    return diagnostic


def _target_name(target: Any) -> str:
    if isinstance(target, str):
        return target
    name = getattr(target, "name", None)
    return str(name or "")


def _target_position(env: Any, target: Any) -> Any:
    shape = getattr(target, "shape", None)
    if shape == (3,):
        return target
    if hasattr(target, "position"):
        return getattr(target, "position")
    if isinstance(target, str):
        try:
            om = env.object_managers[env.current_batch_index]
            return getattr(om.get_object_by_name(target), "position", None)
        except Exception:
            return None
    return None


def _radius_range(value: Any) -> tuple[float, float] | None:
    try:
        radius_min, radius_max = value
        return float(radius_min), float(radius_max)
    except Exception:
        return None


def _radius_band_counts(target_dist: Any, radius_max: float) -> list[dict[str, Any]]:
    if radius_max <= 0:
        return []
    bands = sorted({0.25, 0.5, 0.75, 1.0, round(radius_max, 6)})
    rows = []
    previous = 0.0
    for radius in bands:
        if radius > radius_max:
            continue
        count = int(((target_dist > previous) & (target_dist <= radius)).sum())
        rows.append(
            {
                "radius_min_m": previous,
                "radius_max_m": radius,
                "free_point_count": count,
            }
        )
        previous = radius
    if previous < radius_max:
        count = int(((target_dist > previous) & (target_dist <= radius_max)).sum())
        rows.append(
            {
                "radius_min_m": previous,
                "radius_max_m": radius_max,
                "free_point_count": count,
            }
        )
    return rows


def _place_robot_near_call_values(kwargs: dict[str, Any]) -> dict[str, Any]:
    values = {}
    for field in (
        "max_tries",
        "sampling_radius_range",
        "robot_safety_radius",
        "preserve_z",
        "face_target",
        "check_camera_visibility",
    ):
        if field in kwargs:
            values[field] = diagnostic_json_value(kwargs[field])
    target = kwargs.get("target")
    target_name = getattr(target, "name", None)
    if target_name:
        values["target_name"] = str(target_name)
    return values


def _task_sampler_robot_placement_config(task_sampler: Any) -> dict[str, Any]:
    sampler_config = getattr(getattr(task_sampler, "config", None), "task_sampler_config", None)
    fields = (
        "base_pose_sampling_radius_range",
        "robot_safety_radius",
        "check_robot_placement_visibility",
        "robot_object_z_offset",
        "robot_object_z_offset_random_min",
        "robot_object_z_offset_random_max",
        "max_robot_placement_attempts",
    )
    return {
        field: diagnostic_json_value(getattr(sampler_config, field))
        for field in fields
        if sampler_config is not None and hasattr(sampler_config, field)
    }


def _task_sampler_robot_placement_attempt(
    task_sampler: Any,
    env: Any,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    task_config = getattr(getattr(task_sampler, "config", None), "task_config", None)
    pickup_obj_name = str(getattr(task_config, "pickup_obj_name", "") or "")
    attempt: dict[str, Any] = {
        "attempt_index": len(diagnostics.get("robot_placement_attempts") or []) + 1,
        "pickup_obj_name": pickup_obj_name,
    }
    if not pickup_obj_name:
        return attempt
    try:
        asset_uid = task_sampler.get_asset_uid_from_object(env, pickup_obj_name)
        if asset_uid:
            attempt["asset_uid"] = str(asset_uid)
    except Exception as exc:  # pragma: no cover - best-effort diagnostics.
        attempt["asset_uid_error"] = f"{type(exc).__name__}: {exc}"
    try:
        om = env.object_managers[env.current_batch_index]
        pickup_obj = om.get_object_by_name(pickup_obj_name)
        if hasattr(pickup_obj, "position"):
            attempt["pickup_position"] = diagnostic_json_value(pickup_obj.position)
    except Exception as exc:  # pragma: no cover - best-effort diagnostics.
        attempt["pickup_position_error"] = f"{type(exc).__name__}: {exc}"
    return attempt


def _refresh_task_sampler_failure_diagnostics(diagnostics: dict[str, Any]) -> None:
    attempts = diagnostics.get("robot_placement_attempts") or []
    failures = [item for item in attempts if item.get("result") == "failed"]
    diagnostics["robot_placement_attempt_count"] = len(attempts)
    diagnostics["robot_placement_failure_count"] = len(failures)
    diagnostics["place_robot_near_call_count"] = len(
        diagnostics.get("place_robot_near_calls") or []
    )
    scene_diagnostics = diagnostics.get("placement_scene_diagnostics") or []
    diagnostics["placement_scene_diagnostic_count"] = len(scene_diagnostics)
    diagnostics["asset_failure_count"] = len(diagnostics.get("asset_failures") or [])
    grasp_load_attempts = diagnostics.get("grasp_load_attempts") or []
    diagnostics["grasp_load_attempt_count"] = len(grasp_load_attempts)
    diagnostics["grasp_load_failure_count"] = sum(
        1
        for item in grasp_load_attempts
        if isinstance(item, dict) and item.get("result") != "loaded"
    )
    grasp_collision_checks = diagnostics.get("grasp_collision_checks") or []
    diagnostics["grasp_collision_check_count"] = len(grasp_collision_checks)
    diagnostics["zero_noncolliding_grasp_check_count"] = sum(
        1
        for item in grasp_collision_checks
        if isinstance(item, dict) and item.get("zero_noncolliding")
    )
    grasp_failures = diagnostics.get("grasp_failures") or []
    candidate_removals = diagnostics.get("candidate_removals") or []
    diagnostics["grasp_failure_count"] = len(grasp_failures)
    diagnostics["candidate_removal_count"] = len(candidate_removals)
    diagnostics["candidate_effective_removal_count"] = sum(
        1 for item in candidate_removals if isinstance(item, dict) and item.get("effective_removal")
    )
    diagnostics["candidate_name_miss_count"] = sum(
        1
        for item in candidate_removals
        if isinstance(item, dict) and item.get("candidate_name_present_before") is False
    )
    diagnostics["grasp_threshold_exceeded_count"] = sum(
        1 for item in grasp_failures if isinstance(item, dict) and item.get("threshold_exceeded")
    )
    diagnostics["grasp_threshold_crossed_count"] = sum(
        1 for item in grasp_failures if isinstance(item, dict) and item.get("threshold_crossed")
    )
    if failures:
        diagnostics["last_robot_placement_failure"] = failures[-1]
    place_robot_near_calls = diagnostics.get("place_robot_near_calls") or []
    if place_robot_near_calls:
        diagnostics["last_place_robot_near_call"] = place_robot_near_calls[-1]
    if scene_diagnostics:
        diagnostics["last_placement_scene_diagnostic"] = scene_diagnostics[-1]
    if grasp_load_attempts:
        diagnostics["last_grasp_load_attempt"] = grasp_load_attempts[-1]
    if grasp_collision_checks:
        diagnostics["last_grasp_collision_check"] = grasp_collision_checks[-1]
