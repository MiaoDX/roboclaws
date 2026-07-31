"""Compose the package-owned generic Isaac Lab runtime smoke proof."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from roboclaws.backends.isaaclab import smoke_checker
from roboclaws.core import nvidia_eula as eula


@dataclass(frozen=True)
class RuntimeSmokeRequest:
    runtime_python: Path = Path(".venv-isaaclab/bin/python")
    output_dir: Path = Path("output/isaaclab/runtime-smoke")
    stamp: str = ""
    scene_source: str = "roboclaws-generic"
    scene_index: int = 0
    scene_usd_path: Path | None = None
    generated_scene_kind: str = "roboclaws_smoke"
    seed: int = 7
    generated_mess_count: int = 1
    map_bundle: Path | None = None
    include_robot: bool = True
    robot_name: str = "rby1m"
    enable_segmentation: bool = False
    segmentation_data_types: tuple[str, ...] = ()
    segmentation_semantic_filters: tuple[str, ...] = ()
    require_real_rendering: bool = True
    require_usd_stage_loaded: bool = True
    require_local_scene_usd: bool = False
    require_usd_scene_index: bool = True
    require_selected_usd_bindings: bool = True
    require_robot_view_images: bool = True
    require_nonblank_image: bool = True
    require_segmentation_evidence: bool = False
    accept_nvidia_eula: bool = False


def parse_args(argv: list[str] | None = None) -> RuntimeSmokeRequest:
    parser = argparse.ArgumentParser(description="Run the generic Isaac Lab runtime smoke proof.")
    parser.add_argument("--runtime-python", type=Path, default=Path(".venv-isaaclab/bin/python"))
    parser.add_argument("--output-dir", type=Path, default=Path("output/isaaclab/runtime-smoke"))
    parser.add_argument("--stamp", default="")
    parser.add_argument("--scene-source", default="roboclaws-generic")
    parser.add_argument("--scene-index", type=int, default=0)
    parser.add_argument("--scene-usd-path", type=Path)
    parser.add_argument("--generated-scene-kind", default="roboclaws_smoke")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--generated-mess-count", type=int, default=1)
    parser.add_argument("--map-bundle", type=Path)
    parser.add_argument("--include-robot", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--robot-name", default="rby1m")
    parser.add_argument("--enable-segmentation", action="store_true")
    parser.add_argument("--segmentation-data-type", action="append", default=[])
    parser.add_argument("--segmentation-semantic-filter", action="append", default=[])
    parser.add_argument(
        "--require-real-rendering", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument(
        "--require-usd-stage-loaded", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument("--require-local-scene-usd", action="store_true")
    parser.add_argument(
        "--require-usd-scene-index", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument(
        "--require-selected-usd-bindings",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--require-robot-view-images",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.add_argument(
        "--require-nonblank-image", action=argparse.BooleanOptionalAction, default=True
    )
    parser.add_argument("--require-segmentation-evidence", action="store_true")
    parser.add_argument("--accept-nvidia-eula", action="store_true")
    values = vars(parser.parse_args(argv))
    values["segmentation_data_types"] = tuple(values.pop("segmentation_data_type"))
    values["segmentation_semantic_filters"] = tuple(values.pop("segmentation_semantic_filter"))
    return RuntimeSmokeRequest(**values)


def main(argv: list[str] | None = None) -> int:
    return run_runtime_smoke(parse_args(argv))


def run_runtime_smoke(request: RuntimeSmokeRequest) -> int:
    if not eula.accepted(explicit=request.accept_nvidia_eula):
        print(f"error: {eula.required_message('Isaac runtime smoke')}", file=sys.stderr)
        return 2
    eula.record_acceptance()

    run_dir = request.output_dir / (request.stamp or _timestamp())
    run_dir.mkdir(parents=True, exist_ok=True)
    state_path = run_dir / "state.json"
    init_result = run_dir / "init_result.json"
    robot_views_result = run_dir / "robot_views_result.json"
    env = os.environ.copy()

    init_command = build_init_command(request, run_dir=run_dir, state_path=state_path)
    if _run_and_record(init_command, output=init_result, env=env) != 0:
        return 2
    if not state_path.is_file() or state_path.stat().st_size == 0:
        print(f"error: Isaac runtime smoke init did not write state: {state_path}", file=sys.stderr)
        return 2
    robot_views_command = build_robot_views_command(
        request,
        run_dir=run_dir,
        state_path=state_path,
    )
    if _run_and_record(robot_views_command, output=robot_views_result, env=env) != 0:
        return 2
    return smoke_checker.check_runtime_smoke(
        smoke_checker.SmokeCheckRequest(
            init_result=init_result,
            state_path=state_path,
            robot_views_result=robot_views_result,
            require_real_rendering=request.require_real_rendering,
            require_usd_stage_loaded=request.require_usd_stage_loaded,
            require_local_scene_usd=request.require_local_scene_usd,
            require_usd_scene_index=request.require_usd_scene_index,
            require_selected_usd_bindings=request.require_selected_usd_bindings,
            require_robot_view_images=request.require_robot_view_images,
            require_nonblank_image=request.require_nonblank_image,
            require_segmentation_evidence=request.require_segmentation_evidence,
        )
    )


def build_init_command(
    request: RuntimeSmokeRequest,
    *,
    run_dir: Path,
    state_path: Path,
) -> list[str]:
    command = [
        str(request.runtime_python),
        "-m",
        "roboclaws.backends.isaaclab.worker",
        "--state-path",
        str(state_path),
        "init",
        "--run-dir",
        str(run_dir),
        "--seed",
        str(request.seed),
        "--scene-source",
        str(request.scene_source),
        "--scene-index",
        str(request.scene_index),
        "--generated-scene-kind",
        str(request.generated_scene_kind),
        "--generated-mess-count",
        str(request.generated_mess_count),
        "--runtime-mode",
        "real",
    ]
    if request.scene_usd_path is not None:
        command.extend(("--scene-usd-path", str(request.scene_usd_path)))
    if request.include_robot:
        command.extend(("--include-robot", "--robot-name", str(request.robot_name)))
    if request.enable_segmentation or request.require_segmentation_evidence:
        command.append("--enable-segmentation")
        for data_type in request.segmentation_data_types:
            command.extend(("--segmentation-data-type", str(data_type)))
        for instance_name in request.segmentation_semantic_filters:
            command.extend(("--segmentation-semantic-filter", str(instance_name)))
    if request.map_bundle is not None:
        command.extend(("--map-bundle-dir", str(request.map_bundle)))
    return command


def build_robot_views_command(
    request: RuntimeSmokeRequest,
    *,
    run_dir: Path,
    state_path: Path,
) -> list[str]:
    return [
        str(request.runtime_python),
        "-m",
        "roboclaws.backends.isaaclab.worker",
        "--state-path",
        str(state_path),
        "robot_views",
        "--output-dir",
        str(run_dir / "robot_views"),
        "--label",
        "runtime_smoke",
    ]


def _run_and_record(command: list[str], *, output: Path, env: dict[str, str]) -> int:
    completed = subprocess.run(
        command,
        check=False,
        env=env,
        stderr=subprocess.STDOUT,
        stdout=subprocess.PIPE,
        text=True,
    )
    output.write_text(completed.stdout, encoding="utf-8")
    print(completed.stdout, end="")
    return completed.returncode


def _timestamp() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%m%d_%H%M%S")


if __name__ == "__main__":
    raise SystemExit(main())
