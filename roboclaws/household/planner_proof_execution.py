from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from roboclaws.core.json_sources import read_json_object
from roboclaws.household.cleanup_validation import validate_run_result
from roboclaws.household.household_backend_contract import SYNTHETIC_BACKEND
from roboclaws.household.household_runtime_contract import DEFAULT_REALWORLD_TASK
from roboclaws.household.household_world_episode import run_household_world_episode
from roboclaws.household.planner_proof_bundle_runner import run_from_cleanup_result
from roboclaws.household.planner_proof_bundle_validation import validate_bundle_path
from roboclaws.household.subprocess_backend import (
    DEFAULT_MOLMOSPACES_PYTHON,
    MOLMOSPACES_SUBPROCESS_BACKEND,
)

PlannerProofMode = Literal["dry-run", "execute-rerun"]
DEFAULT_MAP_BUNDLE = Path("assets/maps/molmospaces/procthor-10k-val/0")


@dataclass(frozen=True)
class PlannerProofRequest:
    output_dir: Path
    mode: PlannerProofMode = "dry-run"
    seed: int = 7
    task_prompt: str = DEFAULT_REALWORLD_TASK
    generated_mess_count: int = 10
    min_generated_mess_count: int = 5
    map_bundle_dir: Path = DEFAULT_MAP_BUNDLE
    steps: int = 2
    timeout_s: float = 600.0
    stamp: str | None = None
    runner_python: Path = Path(sys.executable)
    molmospaces_python: Path = DEFAULT_MOLMOSPACES_PYTHON


def execute_planner_proof(request: PlannerProofRequest) -> dict[str, Any]:
    _validate_request(request)
    run_root = request.output_dir / (request.stamp or _timestamp())
    cleanup_dir = run_root / "cleanup"
    bundle_dir = run_root / "proof_bundle"
    rerun_dir = run_root / "cleanup_rerun"
    execute = request.mode == "execute-rerun"
    backend = MOLMOSPACES_SUBPROCESS_BACKEND if execute else SYNTHETIC_BACKEND

    cleanup_result = run_household_world_episode(
        output_dir=cleanup_dir,
        seed=request.seed,
        task_prompt=request.task_prompt,
        backend=backend,
        static_fixture_projection_mode="room_only",
        include_robot=execute,
        record_robot_views=execute,
        generated_mess_count=request.generated_mess_count,
        map_bundle_dir=request.map_bundle_dir,
    )
    _validate_cleanup(
        cleanup_result,
        cleanup_dir,
        request=request,
        backend=backend,
        require_robot_views=execute,
    )

    bundle_result = run_from_cleanup_result(
        cleanup_run_result=cleanup_dir / "run_result.json",
        output_dir=bundle_dir,
        runner_python=request.runner_python,
        molmospaces_python=request.molmospaces_python,
        molmospaces_root=None,
        embodiment="rby1m",
        probe_mode="execute",
        steps=request.steps,
        timeout_s=request.timeout_s,
        renderer_device_id=0,
        torch_extensions_dir=run_root / "torch_extensions" if execute else None,
        rby1m_curobo_memory_profile="low",
        execute_probes=execute,
        rerun_cleanup=execute,
        cleanup_output_dir=rerun_dir if execute else None,
    )
    manifest_path = validate_bundle_path(
        Path(bundle_result["manifest_path"]),
        require_proof_outputs=execute,
        require_cleanup_rerun_output=execute,
        require_proof_execution_horizon=True,
    )

    rerun_result_path: Path | None = None
    if execute:
        rerun_result_path = rerun_dir / "run_result.json"
        rerun_result = read_json_object(rerun_result_path, label="planner proof cleanup rerun")
        _validate_cleanup(
            rerun_result,
            rerun_dir,
            request=request,
            backend=MOLMOSPACES_SUBPROCESS_BACKEND,
            require_robot_views=True,
            require_planner_proof=True,
        )

    return {
        "mode": request.mode,
        "status": bundle_result["status"],
        "run_root": str(run_root),
        "cleanup_run_result": str(cleanup_dir / "run_result.json"),
        "proof_bundle_manifest": str(manifest_path),
        "cleanup_rerun_result": str(rerun_result_path) if rerun_result_path else None,
    }


def _validate_cleanup(
    result: dict[str, Any],
    run_dir: Path,
    *,
    request: PlannerProofRequest,
    backend: str,
    require_robot_views: bool,
    require_planner_proof: bool = False,
) -> None:
    validate_run_result(
        result,
        run_dir,
        expect_task=request.task_prompt,
        expect_backend=backend,
        min_generated_mess_count=request.min_generated_mess_count,
        require_robot_views=require_robot_views,
        require_planner_proof_attachment=require_planner_proof,
        require_planner_backed_cleanup_primitives=require_planner_proof,
        require_planner_cleanup_bridge_ready=require_planner_proof,
    )


def _validate_request(request: PlannerProofRequest) -> None:
    if request.mode not in {"dry-run", "execute-rerun"}:
        raise ValueError(f"unsupported planner proof mode: {request.mode}")
    if request.generated_mess_count < request.min_generated_mess_count:
        raise ValueError("generated_mess_count must be >= min_generated_mess_count")
    if request.steps < 1:
        raise ValueError("steps must be >= 1")
    if request.timeout_s <= 0:
        raise ValueError("timeout_s must be positive")


def _timestamp() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%m%d_%H%M")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the package-owned planner proof workflow.")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=("dry-run", "execute-rerun"), default="dry-run")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--task", default=DEFAULT_REALWORLD_TASK)
    parser.add_argument("--generated-mess-count", type=int, default=10)
    parser.add_argument("--min-generated-mess-count", type=int, default=5)
    parser.add_argument("--map-bundle-dir", type=Path, default=DEFAULT_MAP_BUNDLE)
    parser.add_argument("--steps", type=int, default=2)
    parser.add_argument("--timeout-s", type=float, default=600.0)
    parser.add_argument("--stamp")
    parser.add_argument("--runner-python", type=Path, default=Path(sys.executable))
    parser.add_argument("--molmospaces-python", type=Path, default=DEFAULT_MOLMOSPACES_PYTHON)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = execute_planner_proof(
        PlannerProofRequest(
            output_dir=args.output_dir,
            mode=args.mode,
            seed=args.seed,
            task_prompt=args.task,
            generated_mess_count=args.generated_mess_count,
            min_generated_mess_count=args.min_generated_mess_count,
            map_bundle_dir=args.map_bundle_dir,
            steps=args.steps,
            timeout_s=args.timeout_s,
            stamp=args.stamp,
            runner_python=args.runner_python,
            molmospaces_python=args.molmospaces_python,
        )
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
