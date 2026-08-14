#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    repo_root = Path(__file__).resolve().parents[2]
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

import mujoco

from roboclaws.backends.molmospaces import (
    cli,
    protocol,
)
from roboclaws.backends.molmospaces.common import (
    _float_or_zero,
    _json_object_from_text,
    _ok,
    _optional_str,
    _positive_int,
    _read_state,
)
from roboclaws.backends.molmospaces.operations import (
    _write_state,
    close_receptacle,
    done_cleanup,
    frame_comparison_object,
    init_state,
    navigate_to_object,
    navigate_to_receptacle,
    navigate_to_relative_pose,
    navigate_to_waypoint,
    observe,
    open_receptacle,
    pick_object,
    place_inside_object,
    place_object,
    write_camera_views,
    write_robot_views,
    write_snapshot,
)
from roboclaws.backends.molmospaces.perception_runtime import _load_camera_request_from_kwargs
from roboclaws.backends.molmospaces.state_runtime import _read_locations

BACKEND = "molmospaces_subprocess"
API_SEMANTIC_PROVENANCE = "api_semantic"
DEFAULT_RENDER_WIDTH = 540
DEFAULT_RENDER_HEIGHT = 360
_MODEL_DATA_CACHE: dict[tuple[str, str], tuple[mujoco.MjModel, mujoco.MjData]] = {}
_STATE_MUTATING_COMMANDS = {
    "observe",
    "navigate_to_object",
    "navigate_to_waypoint",
    "navigate_to_relative_pose",
    "navigate_to_receptacle",
    "frame_comparison_object",
    "pick",
    "open_receptacle",
    "close_receptacle",
    "place",
    "place_inside",
}
type _WorkerCommandHandler = protocol.WorkerCommandHandler


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    if args.command == "serve":
        serve(args.state_path)
        return
    if args.command == "init":
        result = _init_command(args)
    else:
        result = _run_worker_command(args.state_path, args.command, _cli_command_kwargs(args))
    print(json.dumps(result, sort_keys=True))


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    return cli.build_arg_parser(
        default_render_width=DEFAULT_RENDER_WIDTH,
        default_render_height=DEFAULT_RENDER_HEIGHT,
    ).parse_args(argv)


def _init_command(args: argparse.Namespace) -> dict[str, Any]:
    return init_state(
        state_path=args.state_path,
        seed=args.seed,
        scene_source=args.scene_source,
        scene_index=args.scene_index,
        include_robot=args.include_robot,
        robot_name=args.robot_name,
        generated_mess_count=args.generated_mess_count,
        generated_mess_object_ids=tuple(args.generated_mess_object_id or ()),
        generated_mess_manifest_path=args.generated_mess_manifest_path,
    )


def serve(state_path: Path) -> None:
    protocol.serve_worker(
        state_path,
        run_state_command=run_state_command,
        ok=_ok,
    )


def run_state_command(
    state_path: Path,
    command: str,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    return _run_worker_command(state_path, command, kwargs)


def _run_worker_command(
    state_path: Path,
    command: str,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    return protocol.run_worker_command(
        state_path,
        command,
        kwargs,
        read_state=_read_state,
        write_state=_write_state,
        run_loaded_state_command=_run_loaded_state_command,
    )


def _run_loaded_state_command(
    state: dict[str, Any],
    command: str,
    kwargs: dict[str, Any],
) -> tuple[dict[str, Any], bool]:
    return protocol.run_loaded_state_command(
        state,
        command,
        kwargs,
        handlers=_WORKER_COMMAND_HANDLERS,
        mutating_commands=_STATE_MUTATING_COMMANDS,
    )


def _cli_command_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    return protocol.cli_command_kwargs(args)


def _snapshot_command(state: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    return write_snapshot(
        state,
        Path(str(kwargs["output_path"])),
        str(kwargs.get("title") or ""),
        width=_positive_int(
            kwargs.get("render_width"),
            DEFAULT_RENDER_WIDTH,
            setting_name="render_width",
        ),
        height=_positive_int(
            kwargs.get("render_height"),
            DEFAULT_RENDER_HEIGHT,
            setting_name="render_height",
        ),
    )


def _robot_views_command(state: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    return write_robot_views(
        state,
        Path(str(kwargs["output_dir"])),
        str(kwargs["label"]),
        focus_object_id=_optional_str(kwargs.get("focus_object_id")),
        focus_receptacle_id=_optional_str(kwargs.get("focus_receptacle_id")),
        camera_yaw_offset_deg=_float_or_zero(
            kwargs.get("camera_yaw_offset_deg"),
            setting_name="camera_yaw_offset_deg",
        ),
        camera_pitch_offset_deg=_float_or_zero(
            kwargs.get("camera_pitch_offset_deg"),
            setting_name="camera_pitch_offset_deg",
        ),
        width=_positive_int(
            kwargs.get("render_width"),
            DEFAULT_RENDER_WIDTH,
            setting_name="render_width",
        ),
        height=_positive_int(
            kwargs.get("render_height"),
            DEFAULT_RENDER_HEIGHT,
            setting_name="render_height",
        ),
    )


def _camera_views_command(state: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    width = _positive_int(
        kwargs.get("render_width"),
        DEFAULT_RENDER_WIDTH,
        setting_name="render_width",
    )
    height = _positive_int(
        kwargs.get("render_height"),
        DEFAULT_RENDER_HEIGHT,
        setting_name="render_height",
    )
    camera_request = _load_camera_request_from_kwargs(kwargs, width=width, height=height)
    return write_camera_views(
        state,
        Path(str(kwargs["output_dir"])),
        camera_request,
        width=width,
        height=height,
    )


def _observe_command(state: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    del kwargs
    return observe(state)


def _locations_command(state: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    del kwargs
    return _ok("locations", final_locations=_read_locations(state))


def _navigate_to_object_command(state: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    return navigate_to_object(state, str(kwargs["object_id"]))


def _navigate_to_waypoint_command(state: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    return navigate_to_waypoint(state, _json_object_from_text(str(kwargs["waypoint_json"])))


def _navigate_to_relative_pose_command(
    state: dict[str, Any],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    return navigate_to_relative_pose(
        state,
        forward_m=_float_or_zero(kwargs.get("forward_m"), setting_name="forward_m"),
        lateral_m=_float_or_zero(kwargs.get("lateral_m"), setting_name="lateral_m"),
        yaw_delta_deg=_float_or_zero(kwargs.get("yaw_delta_deg"), setting_name="yaw_delta_deg"),
    )


def _navigate_to_receptacle_command(
    state: dict[str, Any],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    return navigate_to_receptacle(state, str(kwargs["receptacle_id"]))


def _frame_comparison_object_command(
    state: dict[str, Any],
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    return frame_comparison_object(state, str(kwargs["object_id"]))


def _pick_command(state: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    return pick_object(state, str(kwargs["object_id"]))


def _open_receptacle_command(state: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    return open_receptacle(state, str(kwargs["receptacle_id"]))


def _close_receptacle_command(state: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    return close_receptacle(state, str(kwargs["receptacle_id"]))


def _place_command(state: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    return place_object(state, str(kwargs["receptacle_id"]))


def _place_inside_command(state: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    return place_inside_object(state, str(kwargs["receptacle_id"]))


def _done_command(state: dict[str, Any], kwargs: dict[str, Any]) -> dict[str, Any]:
    return done_cleanup(state, str(kwargs.get("reason") or ""))


_WORKER_COMMAND_HANDLERS: dict[str, _WorkerCommandHandler] = {
    "observe": _observe_command,
    "locations": _locations_command,
    "snapshot": _snapshot_command,
    "robot_views": _robot_views_command,
    "camera_views": _camera_views_command,
    "navigate_to_object": _navigate_to_object_command,
    "navigate_to_waypoint": _navigate_to_waypoint_command,
    "navigate_to_relative_pose": _navigate_to_relative_pose_command,
    "navigate_to_receptacle": _navigate_to_receptacle_command,
    "frame_comparison_object": _frame_comparison_object_command,
    "pick": _pick_command,
    "open_receptacle": _open_receptacle_command,
    "close_receptacle": _close_receptacle_command,
    "place": _place_command,
    "place_inside": _place_inside_command,
    "done": _done_command,
}
