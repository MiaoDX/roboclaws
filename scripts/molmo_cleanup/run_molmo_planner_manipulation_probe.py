#!/usr/bin/env python3
from __future__ import annotations

import argparse
import faulthandler
import json
import os
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from roboclaws.household.subprocess_backend import (  # noqa: E402
    DEFAULT_MOLMOSPACES_PYTHON,
)
from scripts.molmo_cleanup import planner_probe_runtime_diagnostics as probe_runtime
from scripts.molmo_cleanup import planner_probe_task_sampler_diagnostics as probe_sampler
from scripts.molmo_cleanup.planner_manipulation_probe_result import (  # noqa: E402
    blockers_from_completed as _blockers_from_completed,
)
from scripts.molmo_cleanup.planner_manipulation_probe_result import (
    process_output_text as _process_output_text,
)
from scripts.molmo_cleanup.planner_manipulation_probe_result import (
    worker_payload_from_stdout as _worker_payload_from_stdout,
)
from scripts.molmo_cleanup.planner_manipulation_probe_result import (
    write_probe_result as _write_probe_result,
)

DEFAULT_MOLMOSPACES_ROOT = Path("/tmp/roboclaws-molmospaces-spike/molmospaces")
PROBE_TASK = "pick_and_place"
_WORKER_EVENT_STARTED_AT = time.monotonic()
_CUDA_MEMORY_SNAPSHOTS: list[dict[str, Any]] = []
_WORKER_EXCEPTION_CONTEXT: dict[str, Any] = {}
CUROBO_LOW_MEMORY_PROFILE: dict[str, dict[str, Any]] = {
    "policy": {
        "batch_size": 1,
        "max_batch_plan_attempts": 1,
    },
    "planner": {
        "num_trajopt_seeds": 1,
        "num_ik_seeds": 16,
        "max_attempts": 1,
        "trajopt_tsteps": 24,
        "enable_finetune_trajopt": False,
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Execute one bound planner proof command for a proof-bundle run."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
    )
    parser.add_argument(
        "--python-executable",
        type=Path,
        default=Path(
            os.environ.get("ROBOCLAWS_MOLMOSPACES_PYTHON", str(DEFAULT_MOLMOSPACES_PYTHON))
        ),
    )
    parser.add_argument("--molmospaces-root", type=Path, default=DEFAULT_MOLMOSPACES_ROOT)
    parser.add_argument("--embodiment", choices=("franka", "rby1m"), default="franka")
    parser.add_argument(
        "--probe-mode", choices=("config_import", "execute"), default="config_import"
    )
    parser.add_argument(
        "--torch-extensions-dir",
        type=Path,
        default=(
            Path(os.environ["TORCH_EXTENSIONS_DIR"])
            if os.environ.get("TORCH_EXTENSIONS_DIR")
            else None
        ),
        help="Optional isolated Torch extension cache directory for CuRobo JIT builds.",
    )
    parser.add_argument(
        "--renderer-device-id",
        type=int,
        default=int(os.environ.get("ROBOCLAWS_MOLMOSPACES_RENDERER_DEVICE_ID", "0")),
        help=(
            "EGL renderer device id for execute-mode probes. Use a negative value to "
            "disable the probe-local headless renderer adapter."
        ),
    )
    parser.add_argument(
        "--rby1m-curobo-memory-profile",
        choices=("none", "low"),
        default="none",
        help="Probe-local RBY1M/CuRobo memory profile. Default leaves upstream settings unchanged.",
    )
    parser.add_argument(
        "--task-sampler-robot-placement-profile",
        choices=("none", "relaxed", "wide"),
        default="none",
        help=(
            "Probe-local task-sampler robot placement profile. Non-default profiles "
            "widen sampling, lower safety radius, disable visibility gating, and "
            "override the actual place_robot_near max_tries call."
        ),
    )
    parser.add_argument("--curobo-policy-batch-size", type=int, default=None)
    parser.add_argument("--curobo-max-batch-plan-attempts", type=int, default=None)
    parser.add_argument("--curobo-num-trajopt-seeds", type=int, default=None)
    parser.add_argument("--curobo-num-ik-seeds", type=int, default=None)
    parser.add_argument("--curobo-max-attempts", type=int, default=None)
    parser.add_argument("--curobo-trajopt-tsteps", type=int, default=None)
    parser.add_argument("--curobo-disable-finetune-trajopt", action="store_true")
    parser.add_argument(
        "--cleanup-object-id",
        default="",
        help=(
            "Optional cleanup object id that the sampled planner task must match before "
            "emitting cleanup primitive binding."
        ),
    )
    parser.add_argument(
        "--cleanup-target-receptacle-id",
        default="",
        help=(
            "Optional cleanup target receptacle id that the sampled planner task must match "
            "before emitting target-side cleanup primitive binding."
        ),
    )
    parser.add_argument(
        "--cleanup-source-receptacle-id",
        default="",
        help="Optional source receptacle id to record in promoted cleanup primitive binding.",
    )
    parser.add_argument(
        "--cleanup-planner-object-id",
        default="",
        help=(
            "Optional planner-facing pickup object name used for sampled-task matching while "
            "cleanup-object-id remains the cleanup-facing id."
        ),
    )
    parser.add_argument(
        "--cleanup-planner-target-receptacle-id",
        default="",
        help=(
            "Optional planner-facing place receptacle name used for sampled-task matching "
            "while cleanup-target-receptacle-id remains the cleanup-facing id."
        ),
    )
    parser.add_argument(
        "--cleanup-scene-xml",
        default="",
        help=(
            "Optional MolmoSpaces scene XML for exact cleanup proof probes. When set, "
            "the worker samples the planner task from the same scene that produced the "
            "cleanup artifact."
        ),
    )
    parser.add_argument(
        "--cleanup-tools",
        default="",
        help="Comma-separated cleanup tools covered by the requested binding.",
    )
    parser.add_argument("--steps", type=int, default=2)
    parser.add_argument("--timeout-s", type=float, default=180.0)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.worker:
        faulthandler.enable(all_threads=True)
        worker_payload = _run_worker_probe(args)
        print(json.dumps(worker_payload, sort_keys=True))
        if not worker_payload.get("ok"):
            raise SystemExit(3)
        return

    run_result = run_probe(
        output_dir=args.output_dir,
        python_executable=args.python_executable,
        molmospaces_root=args.molmospaces_root,
        embodiment=args.embodiment,
        probe_mode=args.probe_mode,
        renderer_device_id=args.renderer_device_id,
        torch_extensions_dir=args.torch_extensions_dir,
        rby1m_curobo_memory_profile=args.rby1m_curobo_memory_profile,
        task_sampler_robot_placement_profile=args.task_sampler_robot_placement_profile,
        curobo_policy_batch_size=args.curobo_policy_batch_size,
        curobo_max_batch_plan_attempts=args.curobo_max_batch_plan_attempts,
        curobo_num_trajopt_seeds=args.curobo_num_trajopt_seeds,
        curobo_num_ik_seeds=args.curobo_num_ik_seeds,
        curobo_max_attempts=args.curobo_max_attempts,
        curobo_trajopt_tsteps=args.curobo_trajopt_tsteps,
        curobo_disable_finetune_trajopt=args.curobo_disable_finetune_trajopt,
        cleanup_object_id=args.cleanup_object_id,
        cleanup_target_receptacle_id=args.cleanup_target_receptacle_id,
        cleanup_source_receptacle_id=args.cleanup_source_receptacle_id,
        cleanup_planner_object_id=args.cleanup_planner_object_id,
        cleanup_planner_target_receptacle_id=args.cleanup_planner_target_receptacle_id,
        cleanup_scene_xml=args.cleanup_scene_xml,
        cleanup_tools=args.cleanup_tools,
        steps=args.steps,
        timeout_s=args.timeout_s,
    )
    print(
        json.dumps(
            {
                "status": run_result["status"],
                "run_result": str(args.output_dir / "run_result.json"),
            }
        )
    )


def run_probe(
    *,
    output_dir: Path,
    python_executable: Path,
    molmospaces_root: Path,
    embodiment: str,
    probe_mode: str,
    renderer_device_id: int,
    torch_extensions_dir: Path | None,
    rby1m_curobo_memory_profile: str,
    task_sampler_robot_placement_profile: str,
    curobo_policy_batch_size: int | None,
    curobo_max_batch_plan_attempts: int | None,
    curobo_num_trajopt_seeds: int | None,
    curobo_num_ik_seeds: int | None,
    curobo_max_attempts: int | None,
    curobo_trajopt_tsteps: int | None,
    curobo_disable_finetune_trajopt: bool,
    cleanup_object_id: str,
    cleanup_target_receptacle_id: str,
    cleanup_source_receptacle_id: str,
    cleanup_planner_object_id: str,
    cleanup_planner_target_receptacle_id: str,
    cleanup_scene_xml: str,
    cleanup_tools: str,
    steps: int,
    timeout_s: float,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = output_dir / "planner_probe_stdout.txt"
    stderr_path = output_dir / "planner_probe_stderr.txt"
    if not python_executable.is_file():
        stdout_path.write_text("", encoding="utf-8")
        stderr_path.write_text("", encoding="utf-8")
        worker_payload: dict[str, Any] | None = None
        return _write_probe_result(
            output_dir=output_dir,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            embodiment=embodiment,
            probe_mode=probe_mode,
            steps=steps,
            worker_payload=worker_payload,
            returncode=127,
            blockers=[
                {
                    "code": "missing_molmospaces_python",
                    "message": f"Missing MolmoSpaces Python executable: {python_executable}",
                }
            ],
        )

    env = os.environ.copy()
    env["PYTHONPATH"] = _prepend_pythonpath(molmospaces_root, env.get("PYTHONPATH"))
    env["PYTHONFAULTHANDLER"] = "1"
    if torch_extensions_dir is not None:
        torch_extensions_dir = torch_extensions_dir.expanduser().resolve()
        torch_extensions_dir.mkdir(parents=True, exist_ok=True)
        env["TORCH_EXTENSIONS_DIR"] = str(torch_extensions_dir)
    worker_renderer_device_id = probe_runtime.renderer_device_id_for_probe(
        probe_mode=probe_mode,
        renderer_device_id=renderer_device_id,
    )
    if worker_renderer_device_id is not None:
        env["MUJOCO_GL"] = "egl"
        env["PYOPENGL_PLATFORM"] = "egl"
        env["ROBOCLAWS_MOLMOSPACES_RENDERER_DEVICE_ID"] = str(worker_renderer_device_id)
    command = [
        str(python_executable),
        str(Path(__file__).resolve()),
        "--worker",
        "--output-dir",
        str(output_dir),
        "--embodiment",
        embodiment,
        "--probe-mode",
        probe_mode,
        "--renderer-device-id",
        str(renderer_device_id),
        "--steps",
        str(steps),
        "--rby1m-curobo-memory-profile",
        rby1m_curobo_memory_profile,
        "--task-sampler-robot-placement-profile",
        task_sampler_robot_placement_profile,
    ]
    if torch_extensions_dir is not None:
        command.extend(["--torch-extensions-dir", str(torch_extensions_dir)])
    _append_optional_int_arg(command, "--curobo-policy-batch-size", curobo_policy_batch_size)
    _append_optional_int_arg(
        command,
        "--curobo-max-batch-plan-attempts",
        curobo_max_batch_plan_attempts,
    )
    _append_optional_int_arg(command, "--curobo-num-trajopt-seeds", curobo_num_trajopt_seeds)
    _append_optional_int_arg(command, "--curobo-num-ik-seeds", curobo_num_ik_seeds)
    _append_optional_int_arg(command, "--curobo-max-attempts", curobo_max_attempts)
    _append_optional_int_arg(command, "--curobo-trajopt-tsteps", curobo_trajopt_tsteps)
    if curobo_disable_finetune_trajopt:
        command.append("--curobo-disable-finetune-trajopt")
    _append_optional_str_arg(command, "--cleanup-object-id", cleanup_object_id)
    _append_optional_str_arg(
        command,
        "--cleanup-target-receptacle-id",
        cleanup_target_receptacle_id,
    )
    _append_optional_str_arg(
        command,
        "--cleanup-source-receptacle-id",
        cleanup_source_receptacle_id,
    )
    _append_optional_str_arg(command, "--cleanup-planner-object-id", cleanup_planner_object_id)
    _append_optional_str_arg(
        command,
        "--cleanup-planner-target-receptacle-id",
        cleanup_planner_target_receptacle_id,
    )
    _append_optional_str_arg(command, "--cleanup-scene-xml", cleanup_scene_xml)
    _append_optional_str_arg(command, "--cleanup-tools", cleanup_tools)
    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
        )
        stdout_path.write_text(completed.stdout, encoding="utf-8")
        stderr_path.write_text(completed.stderr, encoding="utf-8")
        worker_payload = _worker_payload_from_stdout(completed.stdout)
        blockers = _blockers_from_completed(completed.returncode, worker_payload)
        return _write_probe_result(
            output_dir=output_dir,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            embodiment=embodiment,
            probe_mode=probe_mode,
            steps=steps,
            worker_payload=worker_payload,
            returncode=completed.returncode,
            blockers=blockers,
        )
    except subprocess.TimeoutExpired as exc:
        stdout_text = _process_output_text(exc.stdout)
        stderr_text = _process_output_text(exc.stderr)
        stdout_path.write_text(stdout_text, encoding="utf-8")
        stderr_path.write_text(stderr_text, encoding="utf-8")
        worker_payload = _worker_payload_from_stdout(stdout_text)
        return _write_probe_result(
            output_dir=output_dir,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            embodiment=embodiment,
            probe_mode=probe_mode,
            steps=steps,
            worker_payload=worker_payload,
            returncode=124,
            blockers=[{"code": "timeout", "message": f"Probe exceeded {timeout_s:.1f}s"}],
        )


def _run_worker_probe(args: argparse.Namespace) -> dict[str, Any]:
    _WORKER_EXCEPTION_CONTEXT.clear()
    probe_runtime.configure_headless_renderer_env(args)
    _emit_worker_event(
        "worker_start",
        stage="worker_start",
        embodiment=args.embodiment,
        probe_mode=args.probe_mode,
    )
    runtime_diagnostics = probe_runtime.runtime_diagnostics(
        args,
        curobo_memory_profile_request=_curobo_memory_profile_request(args),
    )
    _emit_worker_event(
        "runtime_diagnostics",
        stage="runtime_diagnostics",
        runtime_diagnostics=runtime_diagnostics,
    )
    _record_cuda_memory_snapshot("worker_runtime_diagnostics")
    try:
        if args.embodiment == "franka":
            payload = _probe_franka(args)
        else:
            payload = _probe_rby1m(args)
        _record_cuda_memory_snapshot("worker_success")
        return {
            "ok": True,
            "initial_runtime_diagnostics": runtime_diagnostics,
            "runtime_diagnostics": probe_runtime.runtime_diagnostics(
                args,
                curobo_memory_profile_request=_curobo_memory_profile_request(args),
            ),
            "cuda_memory_snapshots": list(_CUDA_MEMORY_SNAPSHOTS),
            **payload,
        }
    except BaseException as exc:  # noqa: BLE001 - worker must report capability blockers.
        _record_cuda_memory_snapshot("worker_exception")
        final_runtime_diagnostics = probe_runtime.runtime_diagnostics(
            args,
            curobo_memory_profile_request=_curobo_memory_profile_request(args),
        )
        return {
            "ok": False,
            "exception_type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
            "embodiment": args.embodiment,
            "probe_mode": args.probe_mode,
            "execution_attempted": args.probe_mode == "execute",
            "initial_runtime_diagnostics": runtime_diagnostics,
            "runtime_diagnostics": final_runtime_diagnostics,
            "cuda_memory_snapshots": list(_CUDA_MEMORY_SNAPSHOTS),
            **_worker_exception_probe_context(args),
        }


def _emit_worker_event(event: str, **payload: Any) -> None:
    print(
        json.dumps(
            {
                "event": event,
                "elapsed_s": round(time.monotonic() - _WORKER_EVENT_STARTED_AT, 6),
                **payload,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def _record_worker_exception_context(**payload: Any) -> None:
    for key, value in payload.items():
        if value is not None:
            _WORKER_EXCEPTION_CONTEXT[key] = value


def _worker_exception_probe_context(args: argparse.Namespace) -> dict[str, Any]:
    context = {
        "cleanup_task_config": _WORKER_EXCEPTION_CONTEXT.get("cleanup_task_config")
        or probe_sampler.cleanup_task_config_request_from_args(args),
        "task_sampler_robot_placement_profile": _WORKER_EXCEPTION_CONTEXT.get(
            "task_sampler_robot_placement_profile"
        )
        or probe_sampler.task_sampler_robot_placement_profile_request_from_args(args),
        "cleanup_task_sampler_adapter": _WORKER_EXCEPTION_CONTEXT.get(
            "cleanup_task_sampler_adapter"
        )
        or {},
        "requested_cleanup_primitive_binding": _WORKER_EXCEPTION_CONTEXT.get(
            "requested_cleanup_primitive_binding"
        )
        or probe_sampler.requested_cleanup_primitive_binding(args),
        "task_sampler_failure_diagnostics": _WORKER_EXCEPTION_CONTEXT.get(
            "task_sampler_failure_diagnostics"
        )
        or {},
        "image_artifacts": _WORKER_EXCEPTION_CONTEXT.get("image_artifacts") or {},
    }
    for key in (
        "curobo_memory_profile",
        "sampled_task_binding",
        "cleanup_primitive_binding",
        "cleanup_primitive_binding_blockers",
        "policy_exception_context",
    ):
        if key in _WORKER_EXCEPTION_CONTEXT:
            context[key] = _WORKER_EXCEPTION_CONTEXT[key]
    return context


def _record_cuda_memory_snapshot(stage: str) -> dict[str, Any]:
    snapshot = probe_runtime.cuda_memory_snapshot(stage, started_at=_WORKER_EVENT_STARTED_AT)
    _CUDA_MEMORY_SNAPSHOTS.append(snapshot)
    _emit_worker_event("cuda_memory_snapshot", stage=stage, cuda_memory=snapshot)
    return snapshot


def _curobo_memory_profile_request(args: argparse.Namespace) -> dict[str, Any]:
    explicit = _explicit_curobo_memory_overrides(args)
    profile = getattr(args, "rby1m_curobo_memory_profile", "none")
    return {
        "profile": profile,
        "profile_defaults": (
            CUROBO_LOW_MEMORY_PROFILE if profile == "low" else {"policy": {}, "planner": {}}
        ),
        "explicit_overrides": explicit,
        "requested": profile != "none" or bool(explicit["policy"]) or bool(explicit["planner"]),
    }


def _explicit_curobo_memory_overrides(args: argparse.Namespace) -> dict[str, dict[str, Any]]:
    policy: dict[str, Any] = {}
    planner: dict[str, Any] = {}
    if getattr(args, "curobo_policy_batch_size", None) is not None:
        policy["batch_size"] = args.curobo_policy_batch_size
    if getattr(args, "curobo_max_batch_plan_attempts", None) is not None:
        policy["max_batch_plan_attempts"] = args.curobo_max_batch_plan_attempts
    if getattr(args, "curobo_num_trajopt_seeds", None) is not None:
        planner["num_trajopt_seeds"] = args.curobo_num_trajopt_seeds
    if getattr(args, "curobo_num_ik_seeds", None) is not None:
        planner["num_ik_seeds"] = args.curobo_num_ik_seeds
    if getattr(args, "curobo_max_attempts", None) is not None:
        planner["max_attempts"] = args.curobo_max_attempts
    if getattr(args, "curobo_trajopt_tsteps", None) is not None:
        planner["trajopt_tsteps"] = args.curobo_trajopt_tsteps
    if getattr(args, "curobo_disable_finetune_trajopt", False):
        planner["enable_finetune_trajopt"] = False
    return {"policy": policy, "planner": planner}


def _apply_rby1m_curobo_memory_profile(config: Any, args: argparse.Namespace) -> dict[str, Any]:
    request = _curobo_memory_profile_request(args)
    before = _rby1m_curobo_memory_profile_values(config)
    overrides = _merged_curobo_memory_overrides(args)
    policy_config = config.policy_config
    for name, value in overrides["policy"].items():
        setattr(policy_config, name, value)
    for planner_config in _rby1m_curobo_planner_configs(policy_config).values():
        for name, value in overrides["planner"].items():
            setattr(planner_config, name, value)
    after = _rby1m_curobo_memory_profile_values(config)
    return {
        "schema": "rby1m_curobo_memory_profile_v1",
        "profile": args.rby1m_curobo_memory_profile,
        "requested": request["requested"],
        "applied": bool(overrides["policy"] or overrides["planner"]),
        "request": request,
        "applied_overrides": overrides,
        "before": before,
        "after": after,
    }


def _merged_curobo_memory_overrides(args: argparse.Namespace) -> dict[str, dict[str, Any]]:
    policy: dict[str, Any] = {}
    planner: dict[str, Any] = {}
    if getattr(args, "rby1m_curobo_memory_profile", "none") == "low":
        policy.update(CUROBO_LOW_MEMORY_PROFILE["policy"])
        planner.update(CUROBO_LOW_MEMORY_PROFILE["planner"])
    explicit = _explicit_curobo_memory_overrides(args)
    policy.update(explicit["policy"])
    planner.update(explicit["planner"])
    return {"policy": policy, "planner": planner}


def _rby1m_curobo_memory_profile_values(config: Any) -> dict[str, Any]:
    policy_config = config.policy_config
    return {
        "policy": {
            "batch_size": getattr(policy_config, "batch_size", None),
            "max_batch_plan_attempts": getattr(policy_config, "max_batch_plan_attempts", None),
            "enable_collision_avoidance": getattr(
                policy_config,
                "enable_collision_avoidance",
                None,
            ),
        },
        "planners": {
            name: _curobo_planner_memory_values(planner_config)
            for name, planner_config in _rby1m_curobo_planner_configs(policy_config).items()
        },
    }


def _rby1m_curobo_planner_configs(policy_config: Any) -> dict[str, Any]:
    return {
        name: planner_config
        for name, planner_config in {
            "left": getattr(policy_config, "left_curobo_planner_config", None),
            "right": getattr(policy_config, "right_curobo_planner_config", None),
        }.items()
        if planner_config is not None
    }


def _curobo_planner_memory_values(planner_config: Any) -> dict[str, Any]:
    return {
        "num_trajopt_seeds": getattr(planner_config, "num_trajopt_seeds", None),
        "num_ik_seeds": getattr(planner_config, "num_ik_seeds", None),
        "max_attempts": getattr(planner_config, "max_attempts", None),
        "trajopt_tsteps": getattr(planner_config, "trajopt_tsteps", None),
        "enable_finetune_trajopt": getattr(planner_config, "enable_finetune_trajopt", None),
    }


def _probe_franka(args: argparse.Namespace) -> dict[str, Any]:
    _emit_worker_event("franka_config_import_start", stage="franka_config_import")
    from mlspaces_tests.data_generation.config import FrankaPickAndPlaceDroidTestConfig

    _emit_worker_event("franka_config_import_done", stage="franka_config_import")
    _emit_worker_event("franka_config_construct_start", stage="franka_config_construct")
    config = FrankaPickAndPlaceDroidTestConfig()
    config.use_passive_viewer = False
    config.profile = False
    config.use_wandb = False
    cleanup_task_config = probe_sampler.configure_exact_cleanup_task(config, args)
    task_sampler_robot_placement_profile = probe_sampler.apply_task_sampler_robot_placement_profile(
        config,
        args,
    )
    _record_worker_exception_context(
        cleanup_task_config=cleanup_task_config,
        task_sampler_robot_placement_profile=task_sampler_robot_placement_profile,
    )
    policy_cls = config.policy_config.policy_cls
    _emit_worker_event(
        "franka_policy_class_ready",
        stage="franka_policy_class",
        upstream_policy_class=policy_cls.__name__,
        upstream_policy_module=policy_cls.__module__,
    )
    payload: dict[str, Any] = {
        "embodiment": "franka",
        "task": PROBE_TASK,
        "probe_mode": args.probe_mode,
        "upstream_policy_class": policy_cls.__name__,
        "upstream_policy_module": policy_cls.__module__,
        "policy_type": config.policy_config.policy_type,
        "planner_class_available": True,
        "execution_attempted": False,
        "cleanup_task_config": cleanup_task_config,
        "task_sampler_robot_placement_profile": task_sampler_robot_placement_profile,
    }
    if args.probe_mode == "execute":
        payload.update(
            _execute_policy_probe(
                config,
                args.output_dir,
                args.steps,
                renderer_device_id=probe_runtime.renderer_device_id_for_probe(
                    probe_mode=args.probe_mode,
                    renderer_device_id=args.renderer_device_id,
                ),
                requested_cleanup_binding=probe_sampler.requested_cleanup_primitive_binding(args),
                task_sampler_robot_placement_profile=task_sampler_robot_placement_profile,
            )
        )
    return payload


def _probe_rby1m(args: argparse.Namespace) -> dict[str, Any]:
    _emit_worker_event("rby1m_config_import_start", stage="rby1m_config_import")
    from molmo_spaces.data_generation.config.object_manipulation_datagen_configs import (
        RBY1PickAndPlaceDataGenConfig,
    )

    _emit_worker_event("rby1m_config_import_done", stage="rby1m_config_import")
    _emit_worker_event("rby1m_config_construct_start", stage="rby1m_config_construct")
    config = RBY1PickAndPlaceDataGenConfig()
    config.use_passive_viewer = False
    config.profile = False
    config.use_wandb = False
    config.policy_config.server_urls = []
    cleanup_task_config = probe_sampler.configure_exact_cleanup_task(config, args)
    task_sampler_robot_placement_profile = probe_sampler.apply_task_sampler_robot_placement_profile(
        config,
        args,
    )
    _record_worker_exception_context(
        cleanup_task_config=cleanup_task_config,
        task_sampler_robot_placement_profile=task_sampler_robot_placement_profile,
    )
    curobo_memory_profile = _apply_rby1m_curobo_memory_profile(config, args)
    _record_worker_exception_context(curobo_memory_profile=curobo_memory_profile)
    _emit_worker_event(
        "task_sampler_robot_placement_profile_ready",
        stage="task_sampler_robot_placement_profile",
        task_sampler_robot_placement_profile=task_sampler_robot_placement_profile,
    )
    _emit_worker_event(
        "rby1m_curobo_memory_profile_ready",
        stage="rby1m_curobo_memory_profile",
        curobo_memory_profile=curobo_memory_profile,
    )
    policy_cls = config.policy_config.policy_cls
    _emit_worker_event(
        "rby1m_policy_class_ready",
        stage="rby1m_policy_class",
        upstream_policy_class=policy_cls.__name__,
        upstream_policy_module=policy_cls.__module__,
    )
    payload: dict[str, Any] = {
        "embodiment": "rby1m",
        "task": PROBE_TASK,
        "probe_mode": args.probe_mode,
        "upstream_policy_class": policy_cls.__name__,
        "upstream_policy_module": policy_cls.__module__,
        "policy_type": config.policy_config.policy_type,
        "planner_class_available": True,
        "execution_attempted": False,
        "curobo_memory_profile": curobo_memory_profile,
        "cleanup_task_config": cleanup_task_config,
        "task_sampler_robot_placement_profile": task_sampler_robot_placement_profile,
    }
    if args.probe_mode == "execute":
        _emit_worker_event("rby1m_execute_probe_start", stage="rby1m_execute")
        payload.update(
            _execute_policy_probe(
                config,
                args.output_dir,
                args.steps,
                renderer_device_id=probe_runtime.renderer_device_id_for_probe(
                    probe_mode=args.probe_mode,
                    renderer_device_id=args.renderer_device_id,
                ),
                requested_cleanup_binding=probe_sampler.requested_cleanup_primitive_binding(args),
                task_sampler_robot_placement_profile=task_sampler_robot_placement_profile,
            )
        )
        _emit_worker_event(
            "rby1m_execute_probe_done",
            stage="rby1m_execute",
            execution_attempted=payload.get("execution_attempted"),
            steps_executed=payload.get("steps_executed"),
            max_abs_qpos_delta=payload.get("max_abs_qpos_delta"),
        )
    return payload


def _execute_policy_probe(
    config: Any,
    output_dir: Path,
    steps: int,
    *,
    renderer_device_id: int | None,
    requested_cleanup_binding: dict[str, Any],
    task_sampler_robot_placement_profile: dict[str, Any],
) -> dict[str, Any]:
    import numpy as np
    from molmo_spaces.utils.test_utils import run_task_for_steps_with_observations

    renderer_adapter = _prepare_execute_renderer(renderer_device_id)
    sampler_context = _prepare_execute_task_sampler(
        config,
        output_dir,
        requested_cleanup_binding=requested_cleanup_binding,
        task_sampler_robot_placement_profile=task_sampler_robot_placement_profile,
    )
    task, task_binding_context = _sample_execute_task(
        sampler_context["task_sampler"],
        requested_cleanup_binding,
    )
    _emit_worker_event("execute_warp_adapter_start", stage="execute_warp_adapter")
    warp_adapter = probe_runtime.apply_warp_torch_adapter()
    _emit_worker_event(
        "execute_warp_adapter_ready",
        stage="execute_warp_adapter",
        warp_adapter=warp_adapter,
    )
    policy, initial_qpos, final_qpos, initial_obs, final_obs = _run_execute_policy(
        config,
        task,
        steps,
        run_task_for_steps_with_observations,
    )
    image_artifacts = _execute_probe_image_artifacts(
        output_dir,
        initial_obs,
        final_obs,
    )
    max_abs_qpos_delta = float(np.max(np.abs(final_qpos - initial_qpos)))
    _emit_worker_event(
        "execute_probe_evidence_ready",
        stage="execute_probe_evidence",
        steps_executed=steps,
        max_abs_qpos_delta=max_abs_qpos_delta,
        image_artifacts=image_artifacts,
    )
    return {
        "execution_attempted": True,
        "steps_requested": steps,
        "steps_executed": steps,
        "max_abs_qpos_delta": max_abs_qpos_delta,
        "image_artifacts": image_artifacts,
        "policy_phases": [item.get_current_phase() for item in policy.action_primitives],
        "renderer_adapter": renderer_adapter,
        "task_sampler_robot_placement_profile": task_sampler_robot_placement_profile,
        "cleanup_task_sampler_adapter": sampler_context["cleanup_task_sampler_adapter"],
        "task_sampler_failure_diagnostics": sampler_context["task_sampler_failure_diagnostics"],
        "sampled_task_binding": task_binding_context["sampled_task_binding"],
        "requested_cleanup_primitive_binding": requested_cleanup_binding,
        "cleanup_primitive_binding": task_binding_context["cleanup_binding_result"].get(
            "cleanup_primitive_binding"
        ),
        "cleanup_primitive_binding_blockers": task_binding_context["cleanup_binding_result"].get(
            "blockers", []
        ),
    }


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
    task_sampler_failure_diagnostics = probe_sampler.apply_task_sampler_failure_diagnostics_adapter(
        task_sampler,
        task_sampler_robot_placement_profile,
        output_dir=output_dir,
        record_exception_context=_record_worker_exception_context,
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
        "trajectory_index": probe_sampler.diagnostic_json_value(
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


if __name__ == "__main__":
    main()
