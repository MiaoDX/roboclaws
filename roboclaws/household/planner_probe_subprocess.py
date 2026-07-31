from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from roboclaws.household import planner_probe_runtime_diagnostics as probe_runtime
from roboclaws.household.planner_manipulation_probe_result import (
    blockers_from_completed as _blockers_from_completed,
)
from roboclaws.household.planner_manipulation_probe_result import (
    process_output_text as _process_output_text,
)
from roboclaws.household.planner_manipulation_probe_result import (
    worker_payload_from_stdout as _worker_payload_from_stdout,
)
from roboclaws.household.planner_manipulation_probe_result import (
    write_probe_result as _write_probe_result,
)
from roboclaws.household.planner_probe_execution import (
    _append_optional_int_arg,
    _append_optional_str_arg,
    _prepend_pythonpath,
)

PLANNER_PROBE_MODULE = "roboclaws.household.planner_probe"


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
        "-m",
        PLANNER_PROBE_MODULE,
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
