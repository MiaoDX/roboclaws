"""Typed execution policy and argument lowering for household launches."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from roboclaws.launch.plans import LaunchPlan
from roboclaws.launch.runners import _die, _get


@dataclass
class HouseholdExecution:
    plan: LaunchPlan
    kv: dict[str, str]
    seeds: tuple[str, ...]
    output_dir: Path
    task: str
    profile: str
    backend: str
    evidence_lane: str
    perception_mode: str
    visual_grounding: str
    visual_grounding_timeout_s: float | None
    min_generated_mess_count: int
    validation_options: dict[str, bool | float | int | str]

    @property
    def generated_mess_count(self) -> int:
        return self.plan.relocation_count or 0

    @property
    def map_build(self) -> bool:
        return self.plan.intent == "map-build"

    @property
    def open_ended(self) -> bool:
        return self.plan.intent == "open-ended"

    @property
    def checker_flags(self) -> list[str]:
        return validation_flags(self.validation_options)


def resolve_household_execution(
    plan: LaunchPlan,
    *,
    kv: dict[str, str],
) -> HouseholdExecution:
    profile = plan.profile or plan.evidence_mode
    robot_views = _robot_views(kv)
    generated = plan.relocation_count or 0
    backend = "api_semantic_synthetic" if profile == "smoke" else plan.implementation_backend
    perception_mode, validation_options = _profile_policy(
        profile,
        kv=kv,
        robot_views=robot_views,
        generated=generated,
    )
    if is_b1_plan(plan, backend):
        validation_options = _b1_validation_options(
            profile,
            kv=kv,
            default_minimum=generated,
        )
    validation_options = _intent_validation_options(plan, validation_options)
    minimum_raw = _get(kv, "min_generated_mess_count", str(generated))
    timeout = _get(kv, "visual_grounding_timeout_s", "auto")
    return HouseholdExecution(
        plan=plan,
        kv=kv,
        seeds=tuple(_get(kv, "seeds", _get(kv, "seed", "7")).split()),
        output_dir=Path(
            _get(
                kv,
                "output_dir",
                f"output/household/{plan.surface}/{plan.intent}/{plan.dispatch_runner}-{profile}",
            )
        ),
        task=plan.goal_contract.raw_prompt
        or (
            "帮我建立这个房间的 Runtime Metric Map"
            if plan.intent == "map-build"
            else "帮我收拾这个房间"
        ),
        profile=profile,
        backend=backend,
        evidence_lane="world-public-labels" if profile == "smoke" else profile,
        perception_mode=perception_mode,
        visual_grounding=(
            _get(kv, "camera_labeler", "") if profile == "camera-grounded-labels" else "sim"
        ),
        visual_grounding_timeout_s=None if timeout in {"", "auto"} else float(timeout),
        min_generated_mess_count=(generated if minimum_raw == "auto" else int(minimum_raw)),
        validation_options=validation_options,
    )


def common_run_args(execution: HouseholdExecution) -> list[str]:
    args = _robot_args(execution)
    if execution.visual_grounding != "sim":
        args.extend(["--visual-grounding", execution.visual_grounding])
        if execution.visual_grounding_timeout_s is not None:
            args.extend(["--visual-grounding-timeout-s", str(execution.visual_grounding_timeout_s)])
    for object_id in comma_values(_get(execution.kv, "generated_mess_object_ids", "")):
        args.extend(["--generated-mess-object-id", object_id])
    _append_path_options(
        args,
        execution.kv,
        (("runtime_map_prior", "--runtime-map-prior"), ("goal_contract_path", "--goal-contract")),
    )
    if execution.plan.dispatch_runner != "mcp-smoke":
        _append_path_options(
            args,
            execution.kv,
            (
                ("generated_mess_manifest_path", "--generated-mess-manifest-path"),
                ("isaac_scene_usd_path", "--isaac-scene-usd-path"),
            ),
        )
    return args


def record_robot_views(execution: HouseholdExecution) -> bool:
    if execution.profile == "smoke":
        return False
    return execution.profile != "world-public-labels" or _get(
        execution.kv,
        "robot_views",
        "auto",
    ).lower() not in {"off", "false", "0"}


def optional_path(kv: dict[str, str], key: str) -> Path | None:
    value = _get(kv, key, "")
    return Path(value) if value else None


def comma_values(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def is_b1_plan(plan: LaunchPlan, backend: str) -> bool:
    return plan.world == "b1-map12" and backend == "isaaclab_subprocess"


def validation_flags(options: dict[str, bool | float | int | str]) -> list[str]:
    flags: list[str] = []
    for name, value in options.items():
        flag = "--" + name.replace("_", "-")
        if isinstance(value, bool):
            if value:
                flags.append(flag)
        else:
            flags.extend([flag, str(value)])
    return flags


def _robot_views(kv: dict[str, str]) -> str:
    value = _get(kv, "robot_views", "auto").lower()
    if value not in {"auto", "on", "off", "true", "false", "1", "0"}:
        _die(f"unsupported robot_views {value!r} (expected auto|on|off)")
    return value


def _profile_policy(
    profile: str,
    *,
    kv: dict[str, str],
    robot_views: str,
    generated: int,
) -> tuple[str, dict[str, bool | float | int | str]]:
    success_threshold = (generated * 7 + 9) // 10
    if profile == "smoke":
        return "visible_object_detections", {}
    if profile == "world-public-labels":
        options: dict[str, bool | float | int | str] = {
            "require_waypoint_honesty": True,
            "require_real_robot_alignment": True,
            "min_semantic_accepted_count": 5,
            "min_sweep_coverage": 1.0,
        }
        if robot_views not in {"off", "false", "0"}:
            options = {"require_robot_views": True, **options}
        return "visible_object_detections", options
    if profile == "camera-raw-fpv":
        return "raw_fpv_only", {
            "require_robot_views": True,
            "require_raw_fpv_observations": True,
            "require_model_declared_observations": True,
            "min_model_declared_observations": success_threshold,
            "min_model_declared_actions": success_threshold,
            "min_semantic_accepted_count": success_threshold,
            "min_sweep_coverage": 1.0,
        }
    if profile == "camera-grounded-labels":
        return "camera_model_policy", _camera_grounded_validation_options(kv)
    _die(f"unsupported household evidence lane {profile!r}")


def _camera_grounded_validation_options(
    kv: dict[str, str],
) -> dict[str, bool | float | int | str]:
    options: dict[str, bool | float | int | str] = {
        "require_robot_views": True,
        "require_camera_model_policy": True,
    }
    if camera_labeler := _get(kv, "camera_labeler", ""):
        options.update(
            expect_visual_grounding_pipeline=camera_labeler,
            allow_partial_cleanup=True,
            min_sweep_coverage=1.0,
        )
    return options


def _intent_validation_options(
    plan: LaunchPlan,
    options: dict[str, bool | float | int | str],
) -> dict[str, bool | float | int | str]:
    if plan.intent in {"map-build", "open-ended"}:
        options = _drop_cleanup_threshold_options(
            options,
            drop_sweep=plan.intent == "open-ended",
        )
    if plan.intent == "map-build":
        key = (
            "require_runtime_metric_map"
            if plan.dispatch_runner == "openai-agents-live"
            else "require_map_build"
        )
        options[key] = True
    options["require_base_metric_map"] = True
    return options


def _b1_validation_options(
    profile: str,
    *,
    kv: dict[str, str],
    default_minimum: int,
) -> dict[str, bool | float | int | str]:
    minimum_raw = _get(kv, "min_generated_mess_count", str(default_minimum))
    minimum = default_minimum if minimum_raw == "auto" else int(minimum_raw)
    if profile == "world-public-labels":
        return {
            "require_waypoint_honesty": True,
            "require_b1_robot_consumption_proof": True,
            "min_semantic_accepted_count": minimum,
            "min_sweep_coverage": 1.0,
        }
    if profile == "camera-grounded-labels":
        return {
            "require_robot_views": True,
            "require_camera_model_policy": True,
            "expect_visual_grounding_pipeline": _get(kv, "camera_labeler", ""),
            "require_waypoint_honesty": True,
            "require_b1_robot_consumption_proof": True,
            "min_sweep_coverage": 1.0,
        }
    return {}


def _drop_cleanup_threshold_options(
    options: dict[str, bool | float | int | str],
    *,
    drop_sweep: bool,
) -> dict[str, bool | float | int | str]:
    dropped = {
        "min_semantic_accepted_count",
        "min_model_declared_observations",
        "min_model_declared_actions",
        "require_model_declared_observations",
    }
    if drop_sweep:
        dropped.add("min_sweep_coverage")
    return {key: value for key, value in options.items() if key not in dropped}


def _robot_args(execution: HouseholdExecution) -> list[str]:
    if execution.profile == "smoke":
        return []
    args = ["--include-robot", "--robot-name", "rby1m"]
    if record_robot_views(execution):
        args.append("--record-robot-views")
    return args


def _append_path_options(
    args: list[str],
    kv: dict[str, str],
    options: tuple[tuple[str, str], ...],
) -> None:
    for key, flag in options:
        if value := _get(kv, key, ""):
            args.extend([flag, value])
