from __future__ import annotations

from pathlib import Path
from types import MethodType, SimpleNamespace
from typing import Any

from roboclaws.household.manipulation_contract import (
    PLANNER_PROBE_PRIMITIVE_BINDING_SCHEMA,
)
from roboclaws.household.planner_probe_sampler_views import (
    _candidate_name_present,
    _candidate_object_count,
    _candidate_object_names,
)
from roboclaws.household.planner_probe_values import diagnostic_json_value
from roboclaws.household.semantic_timeline import canonical_cleanup_tool_sequence

EXACT_PICKUP_RETRY_BUDGET = 3
TASK_SAMPLER_RELAXED_ROBOT_PLACEMENT_PROFILE: dict[str, dict[str, Any]] = {
    "task_sampler_config": {
        "base_pose_sampling_radius_range": (0.0, 1.2),
        "robot_safety_radius": 0.15,
        "check_robot_placement_visibility": False,
        "max_robot_placement_attempts": 50,
    },
    "place_robot_near_overrides": {
        "max_tries": 50,
        "sampling_radius_range": (0.0, 1.2),
        "robot_safety_radius": 0.15,
        "check_camera_visibility": False,
    },
}
TASK_SAMPLER_WIDE_ROBOT_PLACEMENT_PROFILE: dict[str, dict[str, Any]] = {
    "task_sampler_config": {
        "base_pose_sampling_radius_range": (0.0, 2.0),
        "robot_safety_radius": 0.15,
        "check_robot_placement_visibility": False,
        "max_robot_placement_attempts": 100,
    },
    "place_robot_near_overrides": {
        "max_tries": 100,
        "sampling_radius_range": (0.0, 2.0),
        "robot_safety_radius": 0.15,
        "check_camera_visibility": False,
    },
}


def task_sampler_robot_placement_profile_request_from_args(args: Any) -> dict[str, Any]:
    profile = str(getattr(args, "task_sampler_robot_placement_profile", "none") or "none")
    defaults = _task_sampler_robot_placement_profile_defaults(profile)
    return {
        "schema": "planner_probe_task_sampler_robot_placement_profile_v1",
        "profile": profile,
        "requested": profile != "none",
        "applied": False,
        "profile_defaults": diagnostic_json_value(defaults),
        "applied_overrides": {},
        "place_robot_near_overrides": diagnostic_json_value(
            defaults.get("place_robot_near_overrides") or {}
        ),
        "evidence_note": (
            "Probe-local robot-placement profile request. It is not a cleanup "
            "contract change and does not promote planner-backed readiness by itself."
        ),
    }


def apply_task_sampler_robot_placement_profile(config: Any, args: Any) -> dict[str, Any]:
    request = task_sampler_robot_placement_profile_request_from_args(args)
    sampler_config = getattr(config, "task_sampler_config", None)
    before = _task_sampler_robot_placement_config_from_config(sampler_config)
    profile = request["profile"]
    defaults = _task_sampler_robot_placement_profile_defaults(profile)
    config_overrides = dict(defaults.get("task_sampler_config") or {})
    applied_overrides: dict[str, Any] = {}
    if sampler_config is not None:
        for name, value in config_overrides.items():
            if hasattr(sampler_config, name):
                setattr(sampler_config, name, value)
                applied_overrides[name] = value
    after = _task_sampler_robot_placement_config_from_config(sampler_config)
    result = {
        **request,
        "applied": bool(applied_overrides or defaults.get("place_robot_near_overrides")),
        "applied_overrides": diagnostic_json_value(applied_overrides),
        "place_robot_near_overrides": diagnostic_json_value(
            defaults.get("place_robot_near_overrides") or {}
        ),
        "before": before,
        "after": after,
        "evidence_note": (
            "Probe-local task-sampler robot-placement mitigation. Config fields are "
            "mutated before task-sampler construction and place_robot_near call "
            "arguments are overridden inside the diagnostics adapter so upstream "
            "hardcoded max_tries values remain visible."
        ),
    }
    if profile != "none" and sampler_config is None:
        result["blockers"] = [
            {
                "code": "task_sampler_config_missing",
                "message": "Cannot apply task-sampler robot-placement profile without config.",
            }
        ]
    return result


def _task_sampler_robot_placement_profile_defaults(profile: str) -> dict[str, Any]:
    if profile == "relaxed":
        return TASK_SAMPLER_RELAXED_ROBOT_PLACEMENT_PROFILE
    if profile == "wide":
        return TASK_SAMPLER_WIDE_ROBOT_PLACEMENT_PROFILE
    return {"task_sampler_config": {}, "place_robot_near_overrides": {}}


def _task_sampler_robot_placement_config_from_config(sampler_config: Any) -> dict[str, Any]:
    if sampler_config is None:
        return {}
    return {
        field: diagnostic_json_value(getattr(sampler_config, field))
        for field in (
            "base_pose_sampling_radius_range",
            "robot_safety_radius",
            "check_robot_placement_visibility",
            "robot_object_z_offset",
            "robot_object_z_offset_random_min",
            "robot_object_z_offset_random_max",
            "max_robot_placement_attempts",
        )
        if hasattr(sampler_config, field)
    }


def configure_exact_cleanup_task(config: Any, args: Any) -> dict[str, Any]:
    requested = requested_cleanup_primitive_binding(args)
    scene_xml = str(getattr(args, "cleanup_scene_xml", "") or "")
    planner_object_id = str(requested.get("planner_object_id") or "")
    planner_target_id = str(requested.get("planner_target_receptacle_id") or "")
    blockers = []
    scene_applied = _apply_exact_cleanup_scene_override(config, scene_xml, blockers)
    alias_applied = _apply_exact_cleanup_alias_overrides(
        config,
        planner_object_id=planner_object_id,
        planner_target_id=planner_target_id,
    )
    for attr in ("task_config_preset_exp", "task_config_preset_scn"):
        if hasattr(config, attr):
            setattr(config, attr, None)
    return {
        "schema": "planner_probe_exact_cleanup_task_config_v1",
        "applied": scene_applied or alias_applied,
        "scene_xml": scene_xml,
        "planner_object_id": planner_object_id,
        "planner_target_receptacle_id": planner_target_id,
        "blockers": blockers,
        "evidence_note": (
            "Probe-local config override for sampling a planner task from the cleanup "
            "artifact scene with requested cleanup object/target aliases."
        ),
    }


def _apply_exact_cleanup_scene_override(
    config: Any,
    scene_xml: str,
    blockers: list[dict[str, Any]],
) -> bool:
    if not scene_xml:
        return False
    scene_path = Path(scene_xml)
    if not scene_path.is_file():
        blockers.append(
            {
                "code": "cleanup_scene_xml_missing",
                "message": f"Requested cleanup scene XML does not exist: {scene_xml}",
            }
        )
        return False
    config.scene_dataset = str(scene_path)
    config.data_split = "val"
    config.task_sampler_config.house_inds = [0]
    config.task_sampler_config.samples_per_house = 1
    config.task_sampler_config.max_tasks = 1
    return True


def _apply_exact_cleanup_alias_overrides(
    config: Any,
    *,
    planner_object_id: str,
    planner_target_id: str,
) -> bool:
    task_config = getattr(config, "task_config", None)
    if task_config is None:
        return False
    applied = False
    if planner_object_id:
        task_config.pickup_obj_name = planner_object_id
        if hasattr(config.task_sampler_config, "pickup_obj_name"):
            config.task_sampler_config.pickup_obj_name = planner_object_id
        applied = True
    if planner_target_id:
        if hasattr(task_config, "place_receptacle_name"):
            task_config.place_receptacle_name = planner_target_id
        if hasattr(task_config, "place_target_name"):
            task_config.place_target_name = planner_target_id
        if hasattr(config.task_sampler_config, "place_target_name"):
            config.task_sampler_config.place_target_name = planner_target_id
        applied = True
    return applied


def cleanup_task_config_request_from_args(args: Any) -> dict[str, Any]:
    requested = requested_cleanup_primitive_binding(args)
    scene_xml = str(getattr(args, "cleanup_scene_xml", "") or "")
    blockers = []
    if scene_xml and not Path(scene_xml).is_file():
        blockers.append(
            {
                "code": "cleanup_scene_xml_missing",
                "message": f"Requested cleanup scene XML does not exist: {scene_xml}",
            }
        )
    return {
        "schema": "planner_probe_exact_cleanup_task_config_v1",
        "applied": bool(
            scene_xml
            or requested.get("planner_object_id")
            or requested.get("planner_target_receptacle_id")
        ),
        "scene_xml": scene_xml,
        "planner_object_id": str(requested.get("planner_object_id") or ""),
        "planner_target_receptacle_id": str(requested.get("planner_target_receptacle_id") or ""),
        "blockers": blockers,
        "evidence_note": (
            "Probe-local config request for sampling a planner task from the cleanup "
            "artifact scene with requested cleanup object/target aliases."
        ),
    }


def apply_exact_cleanup_task_sampler_adapter(
    task_sampler: Any,
    requested_cleanup_binding: dict[str, Any],
) -> dict[str, Any]:
    planner_object_id = str(
        requested_cleanup_binding.get("planner_object_id")
        or requested_cleanup_binding.get("object_id")
        or ""
    )
    planner_target_id = str(
        requested_cleanup_binding.get("planner_target_receptacle_id")
        or requested_cleanup_binding.get("target_receptacle_id")
        or ""
    )
    if not planner_target_id:
        return {
            "schema": "planner_probe_exact_cleanup_task_sampler_adapter_v1",
            "applied": False,
            "reason": "no_requested_planner_target",
        }
    if not (
        hasattr(task_sampler, "_get_place_target_candidates")
        and hasattr(task_sampler, "_prepare_place_target")
    ):
        return {
            "schema": "planner_probe_exact_cleanup_task_sampler_adapter_v1",
            "applied": False,
            "reason": "task_sampler_has_no_place_target_hooks",
            "task_sampler_class": type(task_sampler).__name__,
            "planner_target_receptacle_id": planner_target_id,
        }

    def exact_place_target_candidates(
        self: Any,
        env: Any,
        pickup_obj_name: str,
        supporting_geom_id: int,
    ) -> list[str]:
        return [planner_target_id]

    def exact_prepare_place_target(
        self: Any,
        env: Any,
        place_target_name: str,
        pickup_obj_name: str,
        pickup_obj_pos: Any,
        supporting_geom_id: int,
    ) -> bool:
        om = env.object_managers[env.current_batch_index]
        om.get_object_by_name(planner_target_id)
        self.place_receptacle_name = planner_target_id
        return True

    task_sampler._get_place_target_candidates = MethodType(  # noqa: SLF001
        exact_place_target_candidates,
        task_sampler,
    )
    task_sampler._prepare_place_target = MethodType(  # noqa: SLF001
        exact_prepare_place_target,
        task_sampler,
    )
    adapter = {
        "schema": "planner_probe_exact_cleanup_task_sampler_adapter_v1",
        "applied": True,
        "task_sampler_class": type(task_sampler).__name__,
        "planner_object_id": planner_object_id,
        "planner_target_receptacle_id": planner_target_id,
        "hooks": ["_get_place_target_candidates", "_prepare_place_target"],
        "evidence_note": (
            "Probe-local adapter makes the upstream pick-and-place sampler use the "
            "cleanup request's object and target instead of unrelated generated candidates."
        ),
    }
    select_pickup_object = getattr(task_sampler, "_select_pickup_object", None)
    reset = getattr(task_sampler, "reset", None)
    if planner_object_id and callable(select_pickup_object):

        def exact_select_pickup_object(self: Any, env: Any) -> Any:
            _apply_exact_pickup_candidate_binding(self, planner_object_id, adapter)
            return select_pickup_object(env)

        task_sampler._select_pickup_object = MethodType(  # noqa: SLF001
            exact_select_pickup_object,
            task_sampler,
        )
        adapter["hooks"].append("_select_pickup_object_exact_pickup_candidate_pool")
    elif planner_object_id and callable(reset):

        def exact_reset(self: Any, *args: Any, **kwargs: Any) -> Any:
            result = reset(*args, **kwargs)
            _apply_exact_pickup_candidate_binding(self, planner_object_id, adapter)
            return result

        task_sampler.reset = MethodType(exact_reset, task_sampler)
        adapter["hooks"].append("reset_exact_pickup_candidate_pool")
    return adapter


def _apply_exact_pickup_candidate_binding(
    task_sampler: Any,
    planner_object_id: str,
    adapter: dict[str, Any],
) -> None:
    candidate_objects = getattr(task_sampler, "candidate_objects", None)
    binding = {
        "schema": "planner_probe_exact_pickup_candidate_binding_v1",
        "planner_object_id": planner_object_id,
        "retry_budget": EXACT_PICKUP_RETRY_BUDGET,
        "retry_budget_applied": False,
        "candidate_count_before": _candidate_object_count(task_sampler),
        "candidate_names_before": _candidate_object_names(task_sampler),
        "requested_present_before": None,
        "candidate_count_after": None,
        "candidate_names_after": None,
        "requested_present_after": None,
        "action": "no_candidate_pool",
    }
    if candidate_objects is None:
        adapter["exact_pickup_candidate_binding"] = binding
        return
    try:
        candidates = list(candidate_objects)
    except TypeError:
        adapter["exact_pickup_candidate_binding"] = binding
        return
    matches = [item for item in candidates if str(getattr(item, "name", item)) == planner_object_id]
    binding["requested_present_before"] = bool(matches)
    if matches:
        task_sampler.candidate_objects = _repeat_candidate_objects(
            matches,
            EXACT_PICKUP_RETRY_BUDGET,
        )
        binding["action"] = "filtered_to_requested_candidate"
    else:
        task_sampler.candidate_objects = _repeat_candidate_objects(
            [SimpleNamespace(name=planner_object_id)],
            EXACT_PICKUP_RETRY_BUDGET,
        )
        binding["action"] = "injected_requested_candidate_name"
    binding["retry_budget_applied"] = int(binding["candidate_count_before"] or 0) != len(
        task_sampler.candidate_objects
    )
    binding["candidate_count_after"] = _candidate_object_count(task_sampler)
    binding["candidate_names_after"] = _candidate_object_names(task_sampler)
    binding["requested_present_after"] = _candidate_name_present(
        binding["candidate_names_after"],
        planner_object_id,
    )
    adapter["exact_pickup_candidate_binding"] = binding


def _repeat_candidate_objects(candidates: list[Any], retry_budget: int) -> list[Any]:
    if retry_budget <= 0 or len(candidates) >= retry_budget:
        return list(candidates)
    return [candidates[index % len(candidates)] for index in range(retry_budget)]


def sampled_task_binding(task: Any) -> dict[str, Any]:
    task_config = getattr(getattr(task, "config", None), "task_config", None)
    pickup_obj_name = str(getattr(task_config, "pickup_obj_name", "") or "")
    place_receptacle_name = str(getattr(task_config, "place_receptacle_name", "") or "")
    place_target_name = str(getattr(task_config, "place_target_name", "") or "")
    binding = {
        "schema": "planner_probe_sampled_task_binding_v1",
        "pickup_obj_name": pickup_obj_name,
        "place_receptacle_name": place_receptacle_name,
        "place_target_name": place_target_name,
    }
    description = getattr(task, "get_task_description", None)
    if callable(description):
        try:
            binding["task_description"] = str(description())
        except Exception as exc:  # pragma: no cover - diagnostic only
            binding["task_description_error"] = f"{type(exc).__name__}: {exc}"
    return binding


def requested_cleanup_primitive_binding(args: Any) -> dict[str, Any]:
    object_id = str(getattr(args, "cleanup_object_id", "") or "")
    target_receptacle_id = str(getattr(args, "cleanup_target_receptacle_id", "") or "")
    source_receptacle_id = str(getattr(args, "cleanup_source_receptacle_id", "") or "")
    planner_object_id = str(getattr(args, "cleanup_planner_object_id", "") or "")
    planner_target_receptacle_id = str(
        getattr(args, "cleanup_planner_target_receptacle_id", "") or ""
    )
    tools = cleanup_tools_from_arg(str(getattr(args, "cleanup_tools", "") or ""))
    requested = bool(
        object_id
        or target_receptacle_id
        or source_receptacle_id
        or planner_object_id
        or planner_target_receptacle_id
        or tools
    )
    return {
        "schema": PLANNER_PROBE_PRIMITIVE_BINDING_SCHEMA,
        "requested": requested,
        "object_id": object_id,
        "target_receptacle_id": target_receptacle_id,
        "source_receptacle_id": source_receptacle_id,
        "scene_xml": str(getattr(args, "cleanup_scene_xml", "") or ""),
        "planner_object_id": planner_object_id,
        "planner_target_receptacle_id": planner_target_receptacle_id,
        "tools": tools,
    }


def cleanup_primitive_binding_from_sampled_task(
    requested: dict[str, Any],
    sampled: dict[str, Any],
) -> dict[str, Any]:
    if not requested.get("requested"):
        return {
            "requested": False,
            "promoted": False,
            "cleanup_primitive_binding": None,
            "blockers": [],
        }
    blockers = []
    requested_object = str(requested.get("object_id") or "")
    requested_planner_object = str(requested.get("planner_object_id") or requested_object)
    sampled_object = str(sampled.get("pickup_obj_name") or "")
    if requested_planner_object != sampled_object:
        blockers.append(
            {
                "code": "cleanup_binding_object_mismatch",
                "message": (
                    f"Requested planner object_id={requested_planner_object} does not match "
                    f"sampled pickup_obj_name={sampled_object}."
                ),
            }
        )
    requested_target = str(requested.get("target_receptacle_id") or "")
    requested_planner_target = str(
        requested.get("planner_target_receptacle_id") or requested_target
    )
    sampled_target = str(
        sampled.get("place_receptacle_name") or sampled.get("place_target_name") or ""
    )
    if requested_planner_target and requested_planner_target != sampled_target:
        blockers.append(
            {
                "code": "cleanup_binding_target_mismatch",
                "message": (
                    f"Requested planner target_receptacle_id={requested_planner_target} "
                    "does not match "
                    f"sampled place_receptacle_name={sampled_target}."
                ),
            }
        )
    tools = list(requested.get("tools") or [])
    if not tools:
        blockers.append(
            {
                "code": "cleanup_binding_missing_tools",
                "message": "Requested cleanup binding must include at least one tool.",
            }
        )
    if blockers:
        return {
            "requested": True,
            "promoted": False,
            "cleanup_primitive_binding": None,
            "blockers": blockers,
            "sampled_task_binding": sampled,
            "requested_cleanup_primitive_binding": requested,
        }
    return {
        "requested": True,
        "promoted": True,
        "cleanup_primitive_binding": {
            "schema": PLANNER_PROBE_PRIMITIVE_BINDING_SCHEMA,
            "object_id": requested_object,
            "target_receptacle_id": requested_target,
            "source_receptacle_id": str(requested.get("source_receptacle_id") or ""),
            "tools": canonical_cleanup_tool_sequence(tools),
            "planner_object_id": requested_planner_object,
            "planner_target_receptacle_id": requested_planner_target,
            "sampled_task_binding": sampled,
            "evidence_note": "Requested cleanup primitive binding matched sampled planner task.",
        },
        "blockers": [],
    }


def cleanup_tools_from_arg(value: str) -> list[str]:
    return canonical_cleanup_tool_sequence(value)
