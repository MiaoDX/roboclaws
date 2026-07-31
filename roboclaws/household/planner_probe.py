#!/usr/bin/env python3
from __future__ import annotations

import argparse
import faulthandler
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

from roboclaws.household import planner_probe_runtime_diagnostics as probe_runtime
from roboclaws.household import planner_probe_sampler_contract as probe_sampler
from roboclaws.household.planner_probe_execution import (
    _execute_probe_image_artifacts,
    _prepare_execute_renderer,
    _prepare_execute_task_sampler,
    _run_execute_policy,
    _sample_execute_task,
)
from roboclaws.household.planner_probe_memory import (
    _apply_rby1m_curobo_memory_profile,
    _curobo_memory_profile_request,
)
from roboclaws.household.planner_probe_subprocess import run_probe
from roboclaws.household.planner_probe_worker_diagnostics import (
    _CUDA_MEMORY_SNAPSHOTS,
    _WORKER_EXCEPTION_CONTEXT,
    _emit_worker_event,
    _record_cuda_memory_snapshot,
    _record_worker_exception_context,
    _worker_exception_probe_context,
)
from roboclaws.household.subprocess_backend import (  # noqa: E402
    DEFAULT_MOLMOSPACES_PYTHON,
)

DEFAULT_MOLMOSPACES_ROOT = Path("/tmp/roboclaws-molmospaces-spike/molmospaces")
PROBE_TASK = "pick_and_place"


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
