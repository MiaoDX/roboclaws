"""Live eval provider command, configuration, and artifact-result handling."""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any

from roboclaws.core.backend_catalog import BACKEND_SPECS
from roboclaws.core.goals import normalize_goal_contract
from roboclaws.core.task_intents import TASK_INTENT_SPECS
from roboclaws.evals import live_long_horizon
from roboclaws.evals.live_artifacts import load_live_eval_json
from roboclaws.evals.long_horizon_contract import generated_mess_object_ids
from roboclaws.evals.models import (
    MISSING_NOT_APPLICABLE,
    MISSING_SENTINELS,
    MISSING_UNAVAILABLE,
    EvalSample,
)
from roboclaws.household.household_backend_contract import SYNTHETIC_BACKEND
from roboclaws.household.tasks import HOUSEHOLD_PRESET_SPECS, HOUSEHOLD_TASK_SPECS
from roboclaws.worlds.molmospaces.map_bundles import molmospaces_nav2_map_bundle_path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LIVE_WALL_CLOCK_BUDGET_S = 1500.0
DEFAULT_LIVE_STALL_TIMEOUT_S = 180.0
LIVE_PROCESS_POLL_S = 1.0


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
        f"world={sample.world if sample else 'molmospaces/procthor-10k-val/0'}",
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
    command += live_long_horizon.relocation_args(
        kwargs,
        relocation_count=_generated_mess_count(kwargs),
    )
    port = str(kwargs.get("port") or "")
    if port:
        command.append(f"port={port}")
    runtime_map_prior = str(kwargs.get("runtime_map_prior_path") or "")
    if runtime_map_prior:
        command.append(f"runtime_map_prior={runtime_map_prior}")
    task_prompt = str(kwargs.get("task_prompt") or "")
    if task_prompt and (sample is None or sample.prompt not in {"", MISSING_NOT_APPLICABLE}):
        command.append(f"prompt={task_prompt}")
    return command


def live_surface_run_dir(kwargs: dict[str, Any], *, output_dir: Path) -> Path:
    """Return the preferred artifact directory for one public surface run."""

    return output_dir / f"seed-{int(kwargs['seed'])}"


def _live_surface_already_complete(
    effective_run_dir: Path,
    *,
    require_terminal_status: bool,
) -> bool:
    if (effective_run_dir / "run_result.json").is_file() and not require_terminal_status:
        status = _load_json(effective_run_dir / "live_status.json")
        if status:
            exit_status = status.get("exit_status")
            if exit_status not in {None, 0}:
                _raise_for_terminal_live_status(effective_run_dir, status)
        return True
    return _live_surface_run_is_terminal(effective_run_dir)


def live_wall_clock_budget_s(kwargs: dict[str, Any]) -> float:
    timeout_s = kwargs.get("live_timeout_s")
    if timeout_s is None:
        return DEFAULT_LIVE_WALL_CLOCK_BUDGET_S
    return _positive_timeout_value(timeout_s, "live_timeout_s")


def live_stall_timeout_s(kwargs: dict[str, Any]) -> float:
    timeout_s = kwargs.get("live_stall_timeout_s")
    if timeout_s is None:
        return DEFAULT_LIVE_STALL_TIMEOUT_S
    return _positive_timeout_value(timeout_s, "live_stall_timeout_s")


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
    live_stall_timeout_s: float | None,
    skill_delivery_cell: str = "static-full",
    model_visible_tool_surface: tuple[str, ...] | list[str] = (),
    skill_source_root: Path | None = None,
) -> dict[str, Any]:
    """Return product-run kwargs plus live-agent routing metadata."""

    kwargs = product_run_kwargs(
        sample,
        run_dir=run_dir,
        budget=budget,
        dependency_artifacts=dependency_artifacts,
    )
    live_long_horizon.attach_generated_mess_manifest(kwargs, sample=sample, run_dir=run_dir)
    kwargs.update(
        {
            "eval_sample": sample,
            "agent_engine": agent_engine,
            "provider_profile": provider_profile,
            "model": model,
            "live_timeout_s": live_timeout_s,
            "live_stall_timeout_s": live_stall_timeout_s,
            "skill_delivery_cell": skill_delivery_cell,
            "model_visible_tool_surface": list(model_visible_tool_surface),
            "skill_source_root": str(skill_source_root) if skill_source_root is not None else "",
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

    kwargs: dict[str, Any] = {
        "output_dir": run_dir,
        "seed": sample.seed,
        "task_prompt": task_prompt(sample),
        "backend": implementation_backend(sample, budget=budget),
        "evidence_lane": evidence_lane(sample, budget=budget),
        "intent": sample.intent,
        "generated_mess_count": generated_mess_count(sample),
        "generated_mess_object_ids": generated_mess_object_ids(sample),
        "scene_source": scene_source(sample),
        "scene_index": scene_index(sample),
        "run_metadata_overrides": {
            "eval_sample_id": sample.sample_id,
            "eval_sample_version": sample.version,
            "eval_suite_runner": "roboclaws.evals.runner",
        },
        "goal_contract_json": _goal_contract_json(sample),
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
    runtime_map_prior = str((dependency_artifacts or {}).get("runtime_map_prior_path") or "")
    if runtime_map_prior:
        kwargs["runtime_map_prior_path"] = runtime_map_prior
    return kwargs


def _goal_contract_json(sample: EvalSample) -> str:
    surface = HOUSEHOLD_TASK_SPECS.get(sample.surface)
    intent = TASK_INTENT_SPECS.get(sample.intent)
    if surface is None or intent is None or sample.intent not in surface.supported_intents:
        raise ValueError(
            f"eval sample {sample.sample_id!r} has no canonical goal contract route for "
            f"surface={sample.surface!r} intent={sample.intent!r}"
        )

    required_capabilities = intent.required_capabilities
    if sample.preset not in MISSING_SENTINELS:
        preset = HOUSEHOLD_PRESET_SPECS.get(sample.preset)
        if preset is None or preset.intent_id != intent.intent_id:
            raise ValueError(
                f"eval sample {sample.sample_id!r} has invalid preset {sample.preset!r} "
                f"for intent {sample.intent!r}"
            )
        required_capabilities = preset.required_capabilities

    return normalize_goal_contract(
        surface=surface,
        intent=intent,
        raw_prompt="" if sample.prompt in MISSING_SENTINELS else sample.prompt,
        required_capabilities=required_capabilities,
    ).to_json()


def implementation_backend(sample: EvalSample, *, budget: str) -> str:
    if budget == "smoke":
        runtime_requirements = _sample_runtime_requirements(sample)
        if runtime_requirements.get("requires_real_molmospaces_backend") is True:
            backend = BACKEND_SPECS.get(sample.backend)
            return backend.implementation_backend if backend is not None else sample.backend
        return SYNTHETIC_BACKEND
    backend = BACKEND_SPECS.get(sample.backend)
    if backend is None:
        return sample.backend
    return backend.implementation_backend


def evidence_lane(sample: EvalSample, *, budget: str) -> str:
    runtime_requirements = _sample_runtime_requirements(sample)
    smoke = budget == "smoke" and not runtime_requirements.get("requires_product_evidence_lane")
    return "smoke" if smoke else sample.evidence_lane


def _sample_runtime_requirements(sample: EvalSample) -> dict[str, Any]:
    reference = sample.private_goal_reference
    requirements = reference.get("runtime_requirements")
    return dict(requirements) if isinstance(requirements, dict) else {}


def camera_labeler(sample: EvalSample) -> str:
    if sample.evidence_lane != "camera-grounded-labels":
        return ""
    labeler = sample.camera_labeler
    return labeler if labeler not in MISSING_SENTINELS else "grounding-dino"


def task_prompt(sample: EvalSample) -> str:
    if sample.prompt not in {"", MISSING_NOT_APPLICABLE, MISSING_UNAVAILABLE}:
        return sample.prompt
    return (
        "帮我建立这个房间的 Runtime Metric Map"
        if sample.intent == "map-build"
        else "帮我收拾这个房间"
    )


def generated_mess_count(sample: EvalSample) -> int:
    reference = sample.private_goal_reference
    if "generated_mess_count" in reference:
        return _non_negative_int_value(
            reference.get("generated_mess_count"),
            "private_goal_reference.generated_mess_count",
        )
    if object_ids := generated_mess_object_ids(sample):
        return len(object_ids)
    launch_overrides = sample.launch_overrides or {}
    for key in ("generated_mess_count", "relocation_count"):
        value = launch_overrides.get(key)
        if value is not None:
            return _non_negative_int_value(value, f"launch_overrides.{key}")
    if sample.intent == "map-build":
        return 0
    return 10


def scene_source(sample: EvalSample) -> str:
    return _non_empty_string_value(
        (sample.launch_overrides or {}).get("scene_source", "procthor-10k-val"),
        "launch_overrides.scene_source",
    )


def scene_index(sample: EvalSample) -> int:
    return _non_negative_int_value(
        (sample.launch_overrides or {}).get("scene_index", 0),
        "launch_overrides.scene_index",
    )


def live_surface_env(kwargs: dict[str, Any], *, base_env: Any) -> dict[str, str]:
    """Return environment overrides for the selected live agent engine."""

    env = dict(base_env)
    env["ROBOCLAWS_EVAL_SKILL_DELIVERY_CELL"] = str(
        kwargs.get("skill_delivery_cell") or "static-full"
    )
    env["ROBOCLAWS_EVAL_MODEL_VISIBLE_TOOL_SURFACE"] = json.dumps(
        list(kwargs.get("model_visible_tool_surface") or ()), separators=(",", ":")
    )
    telemetry_identity = kwargs.get("telemetry_identity")
    if telemetry_identity:
        env["ROBOCLAWS_EVAL_TELEMETRY_IDENTITY"] = json.dumps(
            telemetry_identity, separators=(",", ":"), sort_keys=True
        )
    skill_source_root = str(kwargs.get("skill_source_root") or "")
    if skill_source_root:
        env["ROBOCLAWS_EVAL_SKILL_SOURCE_ROOT"] = skill_source_root
    provider_profile = str(kwargs.get("provider_profile") or "")
    if provider_profile:
        if kwargs["agent_engine"] == "openai-agents-sdk":
            env["ROBOCLAWS_PROVIDER_PROFILE"] = provider_profile
    model = str(kwargs.get("model") or "")
    if model:
        if kwargs["agent_engine"] == "openai-agents-sdk":
            env["ROBOCLAWS_OPENAI_AGENTS_MODEL"] = model
    return env


def live_evidence_lane(kwargs: dict[str, Any]) -> str:
    lane = str(kwargs.get("evidence_lane") or "")
    return lane if lane and lane != "smoke" else "world-public-labels"


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
    return (
        0
        if value is None or value == ""
        else _non_negative_int_value(value, "generated_mess_count")
    )


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
    if backend in {MISSING_NOT_APPLICABLE, MISSING_UNAVAILABLE, "", "api_semantic_synthetic"}:
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


def _live_surface_run_is_terminal(run_dir: Path) -> bool:
    status = _load_json(run_dir / "live_status.json")
    if not status:
        return False
    exit_status = status.get("exit_status")
    if exit_status == 0:
        return True
    if exit_status not in {None, 0}:
        _raise_for_terminal_live_status(run_dir, status)
    return False


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
